import json
import logging
import os
import subprocess
import lxml.etree as etree
import pyinotify
import utils
import re
from utils import SetEncoder

TARGET_LIB_INTERNAL_PATTERN = "/{}/internal/".format(utils.TARGET_LIB_NAME)
TARGET_LIB_CLASS_PATTERN = "/{}/class/generated-classes.jar".format(utils.TARGET_LIB_NAME)


def watch_resources_start(needed, path):
    class EventHandler(pyinotify.ProcessEvent):
        def process_IN_ACCESS(self, event):
            target_path = os.path.join(path, "target")
            if event.dir:
                classes_path = os.path.join(target_path, "classes")
                test_cls_path = os.path.join(target_path, "test-classes")
                if event.path.startswith((classes_path, test_cls_path)):
                    needed.setdefault("resources-d", set()).add(event.pathname)
            else:
                # skip class
                if not (event.path.startswith(target_path) and event.name.endswith(".class")):
                    needed.setdefault("resources-f", set()).add(event.pathname)

        def process_IN_OPEN(self, event):
            target_path = os.path.join(path, "target")
            if event.dir:
                classes_path = os.path.join(target_path, "classes")
                test_cls_path = os.path.join(target_path, "test-classes")
                if event.path.startswith((classes_path, test_cls_path)):
                    needed.setdefault("resources-d", set()).add(event.pathname)
            else:
                # skip class
                if not (event.path.startswith(target_path) and event.name.endswith(".class")):
                    needed.setdefault("resources-f", set()).add(event.pathname)

    # Exclude patterns from list
    excl_lst = ["src/main/java/",
                "src/test/java/",
                "target/(?!(classes|test-classes))",  # Negative Lookahead, watch classes|test-classes
                "\..*",  # Hidden files
                utils.SOURCE_BASEDIR_NAME,
                utils.TARGET_LIB_NAME]
    # user custom exclude list
    custom_excl_lst = ["spent-addresses-db"]

    excl_lst = excl_lst + custom_excl_lst
    excl_lst = [os.path.join(path, e) for e in excl_lst]

    wm = pyinotify.WatchManager()  # Watch Manager
    mask = pyinotify.IN_ACCESS | pyinotify.IN_OPEN  # watched events

    excl = pyinotify.ExcludeFilter(excl_lst)
    handler = EventHandler()
    notifier = pyinotify.Notifier(wm, handler, timeout=10)
    wm.add_watch(path, mask, rec=True, exclude_filter=excl)
    return notifier


def watch_resources_stop(notifier):
    notifier.read_events()
    notifier.process_events()
    notifier.stop()


def analyze_test_output(needed, prefix, group_prefix, test_output):
    loaded = {}
    for line in test_output:
        if line.startswith("[Loaded "):
            x = line.split()
            key = x[-1][:-1]
            value = x[1].replace(".", "/")
            loaded.setdefault(key, set()).add(value)
    # if loaded is empty
    if not loaded:
        logging.info("Searching dumpstream for loaded log...")
        dumpstreams = [line.split()[-1] for line in test_output if
                       line.startswith("[WARNING] Corrupted ") and os.path.isfile(line.split()[-1])]
        for dumpstream in dumpstreams:
            with open(dumpstream) as f_stream:
                loaded_list = [line.split("[")[1].split("]")[0] for line in f_stream if
                               line.startswith("Corrupted ") and "[Loaded" in line and line.find("[") < line.find("]")]
                for s in loaded_list:
                    x = s.split()
                    key = x[-1]
                    value = x[1].replace(".", "/")
                    loaded.setdefault(key, set()).add(value)
    logging.info("Length of loaded dict: {}".format(len(loaded)))

    for key in loaded.keys():
        if key.endswith("/test-classes/"):
            needed["test-classes"] = loaded[key]
        elif key.endswith("/classes/"):
            needed["classes"] = loaded[key]
        elif key.startswith("file:"):
            internal_jar = None
            if "/repository/" in key:
                repo = key.split("/repository/")[-1]
                group_id = ".".join(repo.split("/")[:-3])
                if group_id.startswith(group_prefix):
                    internal_jar = repo.split("/")[-1]
            elif TARGET_LIB_INTERNAL_PATTERN in key:
                internal_jar = key.split(TARGET_LIB_INTERNAL_PATTERN)[1]
            elif TARGET_LIB_CLASS_PATTERN in key:
                needed["generated-classes"] = loaded[key]
            if internal_jar in needed.get("internal", {}):
                logging.warning("conflict internal jar names in dynamic analysis!")
            if internal_jar:
                needed.setdefault("internal", {})[internal_jar] = loaded[key]
        elif key.endswith("ClassLoader"):
            for clazz in loaded[key]:
                if clazz.startswith(prefix):
                    needed.setdefault("ClassLoader", set()).add(clazz)


def dynamic_test(needed, cwd, source_path, prefix, group_prefix, test_name, add_test_cmds, output_dir, pom):
    if cwd == source_path:
        argLine_prop = "per.argLine"
    else:
        argLine_prop = "argLine"
    cmd = ["mvn", "-f", pom, "surefire:test", "-D{}=-verbose:class".format(argLine_prop), *add_test_cmds.split()]
    if test_name:
        cmd.append("-Dtest={}".format(test_name))
    logging.info(" ".join(cmd))
    test_output_raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd) \
        .stdout.decode('utf-8')
    with open(os.path.join(output_dir, "test.output"), "w") as f:
        f.write(test_output_raw)
    test_output = test_output_raw.splitlines()

    analyze_test_output(needed, prefix, group_prefix, test_output)

    if needed:
        return True
    else:
        return False


def add_internal(needed, line, group_prefix):
    pair = line.split("[")[-1].split("(")
    internal_jar = pair[0].split("/")[-1]
    group_id = None
    if "/repository/" in pair[0]:
        group_id = ".".join(pair[0].split("/repository/")[-1].split("/")[:-3])
    value = pair[1].split(".")[0].strip("/")
    if (group_id and group_id.startswith(group_prefix)) or (
            value.startswith("shaded") and TARGET_LIB_INTERNAL_PATTERN in line):
        needed.setdefault("internal", {}).setdefault(internal_jar, set()).add(value)


def add_generated_classes(needed, line):
    value = line.split("[")[2].split("(")[1].split(".")[0]
    needed.setdefault("generated-classes", set()).add(value)


def add_processor(needed, line):
    _, processor, _ = line.split(maxsplit=2)
    needed.setdefault("processor", set()).add(processor)


def analyze_test_compile_output(needed, group_prefix, test_compile_output):
    for line in test_compile_output:
        if line.startswith("[loading "):
            if TARGET_LIB_CLASS_PATTERN in line:
                add_generated_classes(needed, line)
            elif "/src/test/java/" in line:
                value = line.split("/src/test/java/")[1].split(".")[0]
                needed.setdefault("test-classes", set()).add(value)
            elif "/target/classes/" in line:
                value = line.split("/target/classes/")[1].split(".")[0]
                needed.setdefault("classes", set()).add(value)
            elif any(s in line for s in ("/repository/", TARGET_LIB_INTERNAL_PATTERN)):
                add_internal(needed, line, group_prefix)
        elif line.startswith("[wrote RegularFileObject") and "/target/test-classes/" in line:
            value = line.split("/target/test-classes/")[1].split(".")[0]
            needed.setdefault("test-classes", set()).add(value)
        elif line.startswith("Processor "):
            add_processor(needed, line)


def static_test_compile(needed, cwd, group_prefix, test_name, add_test_cmds, output_dir, pom):
    if "test-classes" not in needed:
        return False
    test_src = [clazz.split("$")[0] + ".java" for clazz in needed["test-classes"]]
    test_compile_output = []
    cmd = ["mvn", "-f", pom, "test-compile", "-Dmaven.compiler.verbose=true",
           "-Dmaven.compiler.failOnError=false", "-Dper.testIncludes={}".format(",".join(test_src)),
           *add_test_cmds.split()]
    if test_name:
        cmd.append("-Dtest={}".format(test_name))
    logging.info(" ".join(cmd))
    both_compile_output_raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd) \
        .stdout.decode('utf-8')
    with open(os.path.join(output_dir, "test-compile.output"), "w") as f:
        f.write(both_compile_output_raw)
    both_compile_output = both_compile_output_raw.splitlines()
    for idx, line in enumerate(both_compile_output):
        if line.startswith("[INFO] ") and "testCompile" in line:
            # "[INFO] " len=7
            #  01234567
            test_compile_output = [line[len("[INFO] "):] if line.startswith("[INFO] ") else line for line in
                                   both_compile_output[idx:]]
            break
    if not test_compile_output:
        logging.info("Cannot find testCompile output!")
        return False

    analyze_test_compile_output(needed, group_prefix, test_compile_output)
    return True


def analyze_compile_output(needed, group_prefix, compile_output):
    for line in compile_output:
        if line.startswith("[loading "):
            if TARGET_LIB_CLASS_PATTERN in line:
                add_generated_classes(needed, line)
            elif "/src/main/java/" in line:
                value = line.split("/src/main/java/")[1].split(".")[0]
                needed.setdefault("classes", set()).add(value)
            elif any(s in line for s in ("/repository/", TARGET_LIB_INTERNAL_PATTERN)):
                add_internal(needed, line, group_prefix)
        elif line.startswith("[wrote RegularFileObject") and "/target/classes/" in line:
            value = line.split("/target/classes/")[1].split(".")[0]
            needed.setdefault("classes", set()).add(value)
        elif line.startswith("Processor "):
            add_processor(needed, line)


def static_compile(needed, cwd, group_prefix, test_name, add_test_cmds, output_dir, pom):
    if "classes" not in needed:
        return False
    compile_src = [clazz.split("$")[0] + ".java" for clazz in needed["classes"]]
    cmd = ["mvn", "-f", pom, "clean", "compile", "-Dmaven.compiler.verbose=true", "-Dmaven.compiler.failOnError=false",
           "-Dper.includes={}".format(",".join(compile_src)), *add_test_cmds.split()]
    if test_name:
        cmd.append("-Dtest={}".format(test_name))
    logging.info(" ".join(cmd))
    compile_output_raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd) \
        .stdout.decode('utf-8')
    with open(os.path.join(output_dir, "compile.output"), "w") as f:
        f.write(compile_output_raw)
    compile_output = [line[len("[INFO] "):] if line.startswith("[INFO] ") else line for line in
                      compile_output_raw.splitlines()]

    analyze_compile_output(needed, group_prefix, compile_output)
    return True


def maven_setting(needed, cwd, add_test_cmds, output_dir, pom, setting):
    needed["maven-setting"] = {}
    if not setting.OPT_build:
        return False
    effective_pom = os.path.join(output_dir, "effective-pom.xml")
    cmd = ["mvn", "-f", pom, "--quiet", "help:effective-pom", "-Doutput={}".format(effective_pom),
           *add_test_cmds.split()]
    logging.info(" ".join(cmd))
    subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.exists(effective_pom):
        parser = etree.XMLParser(remove_blank_text=True, encoding='utf-8')
        pom_tree = etree.parse(effective_pom, parser=parser)
        pom_root = pom_tree.getroot()
        NSMAP = {"ns": pom_root.nsmap[None]}

        # Extract compiler configuration
        maven_compiler_source_elm = pom_root.find("properties/maven.compiler.source", pom_root.nsmap)
        maven_compiler_target_elm = pom_root.find("properties/maven.compiler.target", pom_root.nsmap)
        if maven_compiler_source_elm is not None:
            needed["maven-setting"]["maven.compiler.source"] = maven_compiler_source_elm.text
        if maven_compiler_target_elm is not None:
            needed["maven-setting"]["maven.compiler.target"] = maven_compiler_target_elm.text

        # Extract plugins from phases
        plugins_set = set()
        artifactId_excl = ["maven-checkstyle-plugin", "apache-rat-plugin", "forbiddenapis", "license-maven-plugin",
                           "animal-sniffer-maven-plugin", "spotbugs-maven-plugin", "jacoco-maven-plugin",
                           "jprotobuf-precompile-plugin"]
        phases = ["compile", "test-compile", "test"]
        for phase in phases:
            plugin_elms = pom_root.xpath(
                "ns:build/ns:plugins/ns:plugin[ns:executions/ns:execution[ns:phase='{}']]".format(phase),
                namespaces=NSMAP)
            for plugin_elm in plugin_elms:
                artifactId_elm = plugin_elm.find("artifactId", pom_root.nsmap)
                if artifactId_elm is not None and artifactId_elm.text not in artifactId_excl:
                    plugins_set.add(plugin_elm)
        plugins_str = ""
        for plugin in plugins_set:
            plugin_str = etree.tostring(plugin, pretty_print=True, encoding="unicode")
            # remove namespace, ${...}, @{...}
            plugins_str += re.sub(r"\${.*?} ", "",
                                  re.sub(r"@{.*?}", "",
                                         re.sub(r"^<plugin.*?(?<!/)>", "<plugin>", plugin_str)))
        if plugins_str:
            needed["maven-setting"]["plugins"] = "<plugins>\n" + plugins_str + "</plugins>"
        return True
    else:
        return False


def analyze_source_roots(needed, phase, compile_output):
    try:
        roots_idx = compile_output.index("Source roots:")
    except ValueError:
        return
    roots_lst = []
    for idx, line in enumerate(compile_output[roots_idx + 1:]):
        if line.startswith(" "):
            roots_lst.append(line.strip())
        else:
            break
    if roots_lst:
        needed.setdefault("source-roots", {})[phase] = roots_lst


def source_roots(needed, cwd, add_test_cmds, output_dir, pom):
    compile_output = []
    test_compile_output = []
    cmd = ["mvn", "-X", "-f", pom, "clean", "test-compile", "-Dmaven.compiler.failOnError=false",
           *add_test_cmds.split()]
    logging.info(" ".join(cmd))
    both_compile_output_raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             cwd=cwd).stdout.decode('utf-8')
    with open(os.path.join(output_dir, "test-compile-X.output"), "w") as f:
        f.write(both_compile_output_raw)
    both_compile_output = both_compile_output_raw.splitlines()
    for idx, line in enumerate(both_compile_output):
        if line.startswith("[INFO] ") and "testCompile" in line:
            # "[DEBUG] " len=8
            #  012345678
            compile_output = [line[len("[DEBUG] "):] for line in both_compile_output[:idx] if
                              line.startswith("[DEBUG] ")]
            test_compile_output = [line[len("[DEBUG] "):] for line in both_compile_output[idx:] if
                                   line.startswith("[DEBUG] ")]
            break
    if not compile_output and not test_compile_output:
        logging.info("Cannot find compile and test compile output!")
        return False

    analyze_source_roots(needed, "compile", compile_output)
    analyze_source_roots(needed, "test-compile", test_compile_output)
    return True


def extract_deps(cwd, source_path, prefix, group_prefix, test_name, add_test_cmds, output_dir, pom, setting):
    needed = {}

    if setting.OPT_hybrid:
        logging.info("Dependencies analysis - Dynamic: test phase")
    if setting.OPT_resource:
        logging.info("Resources analysis - test - start!")
        notifier = watch_resources_start(needed, source_path)
    else:
        logging.info("Resources analysis - skip!")
    if not dynamic_test(needed, cwd, source_path, prefix, group_prefix, test_name, add_test_cmds, output_dir, pom):
        logging.info("Failed: got empty dependencies for dynamic analysis.")
        return False
    elif setting.OPT_hybrid:
        logging.info("The keys in needed dict: {}".format([key for key in needed]))
        with open(os.path.join(output_dir, "test.json"), "w") as f:
            json.dump(needed, f, cls=SetEncoder)
    if setting.OPT_resource:
        logging.info("Resources analysis - test - stop!")
        watch_resources_stop(notifier)
        logging.info("The keys in needed dict: {}".format([key for key in needed]))
        with open(os.path.join(output_dir, "resources-test.json"), "w") as f:
            json.dump(needed, f, cls=SetEncoder)

    if not setting.OPT_hybrid:
        logging.info("Skip dynamic: test phase")
        needed.pop("classes", "No Key found")
        needed.pop("internal", "No Key found")
        needed.pop("generated-classes", "No Key found")
        needed.pop("ClassLoader", "No Key found")
        needed["test-classes"] = {test_name.split("#")[0].replace(".", "/")}
        logging.info("The keys in needed dict: {}".format([key for key in needed]))
        with open(os.path.join(output_dir, "test.json"), "w") as f:
            json.dump(needed, f, cls=SetEncoder)

    logging.info("Dependencies analysis - Static: test-compile phase")
    logging.info("Pre-compile src...")
    subprocess.run(["mvn", "-f", pom, "clean", "compile", "-Dmaven.compiler.failOnError=false",
                    *add_test_cmds.split()], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not static_test_compile(needed, cwd, group_prefix, test_name, add_test_cmds, output_dir, pom):
        logging.info("Skipped: no test compile dependencies.")
    else:
        logging.info("The keys in needed dict: {}".format([key for key in needed]))
        with open(os.path.join(output_dir, "test-compile.json"), "w") as f:
            json.dump(needed, f, cls=SetEncoder)

    logging.info("Dependencies analysis - Static: compile phase")
    if not static_compile(needed, cwd, group_prefix, test_name, add_test_cmds, output_dir, pom):
        logging.info("Skipped: no compile dependencies.")
    else:
        logging.info("The keys in needed dict: {}".format([key for key in needed]))
        with open(os.path.join(output_dir, "compile.json"), "w") as f:
            json.dump(needed, f, cls=SetEncoder)

    if setting.OPT_build:
        logging.info("Maven setting analysis: effective-pom")
        if not maven_setting(needed, cwd, add_test_cmds, output_dir, pom, setting=setting):
            logging.warning("Cannot extract some Maven setting!")
        else:
            logging.info("The keys in needed dict: {}".format([key for key in needed]))
            with open(os.path.join(output_dir, "build.json"), "w") as f:
                json.dump(needed, f, cls=SetEncoder)
    else:
        logging.info("Maven setting analysis: skip!")

    if setting.OPT_generated:
        logging.info("Source roots analysis: mvn -X")
        if not source_roots(needed, cwd, add_test_cmds, output_dir, pom):
            logging.warning("Cannot extract source roots!")
        else:
            logging.info("The keys in needed dict: {}".format([key for key in needed]))
            with open(os.path.join(output_dir, "roots.json"), "w") as f:
                json.dump(needed, f, cls=SetEncoder)
    else:
        logging.info("Source roots analysis: skip!")

    logging.info("The output directory of dependencies analysis: {}".format(output_dir))
    return needed
