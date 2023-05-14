import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import defaultdict

import packaging.version as pkv

from lxml import etree

TIMEOUT = 15 * 60
SOURCE_BASEDIR_NAME = "pexreport-temp"
TARGET_LIB_NAME = "pexreport-lib"


class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)


def setup_pom(path, src_pom, per_pom):
    logging.info("Set up target pom: {}".format(src_pom))
    parser = etree.XMLParser(remove_blank_text=True, encoding='utf-8')
    pom_tree = etree.parse(src_pom, parser=parser)
    pom_root = pom_tree.getroot()
    # namespace for xpath
    NSMAP = {"ns": pom_root.nsmap[None]}
    # setup properties
    """
    <properties>
        <argLine></argLine>
        <per.argLine></per.argLine>
        <per.includes></per.includes>
        <per.testIncludes></per.testIncludes>
    </properties>
    """
    pom_prop = pom_root.find("properties", pom_root.nsmap)
    if pom_prop is None:
        logging.info("properties not found, create properties")
        pom_prop = etree.fromstring("<properties></properties>")
        pom_root.append(pom_prop)
    for prop_elm in ["argLine", "per.argLine", "per.includes", "per.testIncludes"]:
        if pom_prop.find(prop_elm, pom_root.nsmap) is None:
            pom_prop.append(etree.fromstring("<{}></{}>".format(prop_elm, prop_elm)))

    # setup build
    """
    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <!-- use <version>3.8.1/version> or compatible version-->
                <configuration>
                    <includes>${per.includes}</includes>
                    <testIncludes>${per.testIncludes}</testIncludes>
                </configuration>
            </plugin>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <!-- use <version>2.22.2</version> or compatible version-->
                <configuration>
                    <argLine>${argLine} ${per.argLine}</argLine>
                </configuration>
            </plugin>
        </plugins>
    </build>
    """

    cur_elm = pom_root
    for tag in ["build", "plugins"]:
        ret_elm = cur_elm.find(tag, pom_root.nsmap)
        if ret_elm is None:
            new_elm = etree.fromstring("<{0}></{0}>".format(tag), parser=parser)
            cur_elm.append(new_elm)
            cur_elm = new_elm
        else:
            cur_elm = ret_elm

    compiler_plugin = ["org.apache.maven.plugins", "maven-compiler-plugin", "3.8.1", "3.1",
                       "<includes>${per.includes}</includes><testIncludes>${per.testIncludes}</testIncludes>"]
    surefire_plugin = ["org.apache.maven.plugins", "maven-surefire-plugin", "2.22.2", "2.1",
                       " <argLine>${argLine} ${per.argLine}</argLine>"]

    for groupId, artifactId, version, since_version, config in (compiler_plugin, surefire_plugin):
        # extract current version
        cur_version = None
        cmd = ["mvn", "-Dplugin={}:{}".format(groupId, artifactId), "help:describe"]
        logging.info(" ".join(cmd))
        sys.stdout.flush()
        try:
            version_raw = subprocess.run(cmd, cwd=path, timeout=TIMEOUT, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT).stdout.decode('utf-8')
            logging.info(version_raw)
            for line in version_raw.splitlines():
                if line.startswith("Version: "):
                    cur_version = line.split()[-1].strip()
                    cur_version = cur_version.split("-")[0]
                    break
        except subprocess.TimeoutExpired:
            logging.error("Timeout! Fail to extract version of {}".format(artifactId))
        logging.info("Extracted version: {}".format(cur_version))

        plugin_elms = cur_elm.xpath(
            "ns:plugin[(not(ns:groupId) or ns:groupId='{}') and ns:artifactId='{}']".format(groupId, artifactId),
            namespaces=NSMAP)
        if len(plugin_elms) == 0:
            logging.info("{} not found, creating ...".format(artifactId))
            plg_str = """<plugin>
            <groupId>{}</groupId>
            <artifactId>{}</artifactId>
            <configuration>{}</configuration>
            </plugin>""".format(groupId, artifactId, config)
            plugin_elm = etree.fromstring(plg_str, parser=parser)
            if cur_version and pkv.parse(cur_version) < pkv.parse(since_version):
                plugin_elm.append(etree.fromstring("<version>{}</version>".format(version), parser=parser))
            cur_elm.append(plugin_elm)
        else:
            for plugin_elm in plugin_elms:
                config_elm = plugin_elm.find("configuration", pom_root.nsmap)
                config_etree = etree.fromstring("<configuration>{}</configuration>".format(config), parser=parser)
                if config_elm is None:
                    plugin_elm.append(config_etree)
                else:
                    for elm in config_etree:
                        config_elm.append(elm)
                version_elm = plugin_elm.find("version", pom_root.nsmap)
                if version_elm is None:
                    if cur_version and pkv.parse(cur_version) < pkv.parse(since_version):
                        plugin_elm.append(etree.fromstring("<version>{}</version>".format(version), parser=parser))
                else:
                    if version_elm.text.startswith("${"):
                        if pkv.parse(cur_version) < pkv.parse(since_version):
                            version_elm.text = version
                    else:
                        if pkv.parse(version_elm.text) < pkv.parse(since_version):
                            version_elm.text = version
    pom_tree.write(per_pom, encoding="utf-8", xml_declaration=True, pretty_print=True)


def simple_run(source_path, test_path, test_name=None, add_test_cmds="", pom="pom.xml", timeout=TIMEOUT,
               original_path=None):
    if test_name:
        logging.info("======================"
                     "Compile and run the test case: {}"
                     "======================".format(test_name))
        cmd = ["mvn", "-f", pom, "clean", "test", "-Dtest={}".format(test_name), *add_test_cmds.split()]

    else:
        logging.info("======================"
                     "Compile and run all tests of source project"
                     "======================")
        cmd = ["mvn", "-f", pom, "--quiet", "clean", "test", *add_test_cmds.split()]

    logging.info(" ".join(cmd))
    sys.stdout.flush()
    try:
        output_raw = subprocess.run(cmd, cwd=test_path, timeout=timeout, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT).stdout.decode('utf-8')
        logging.info(output_raw)
    except subprocess.TimeoutExpired:
        logging.error((test_name if test_name else "All tests") + ": failed to run, timeout!")
        return {}, -1

    if test_name:
        logging.info("======================"
                     "End of the running for test case: {}"
                     "======================".format(test_name))
    else:
        logging.info("======================"
                     "End of the compile and run all tests of source project"
                     "======================")

    return extract_failed_tests_with_root_cause(source_path, original_path)


def extract_failed_tests_with_root_cause(source_path, original_path=None):
    failed_tests = defaultdict(dict)
    total_fail = 0

    surefire_reports = os.path.join(source_path, "target/surefire-reports")
    if os.path.exists(surefire_reports):
        xml_files = [file for file in os.listdir(surefire_reports) if os.path.splitext(file)[1] == ".xml"]
        logging.info("The surefire xml reports: {}".format(xml_files))
        xml_paths = [os.path.join(surefire_reports, f) for f in xml_files]
        # Use set to group test cases
        # # Order by last modification
        # xml_paths.sort(key=lambda x: os.path.getmtime(x))
        for xml_path in xml_paths:
            root = etree.parse(xml_path).getroot()
            for element in root.xpath("testcase/error|testcase/failure"):
                total_fail += 1
                testcase = element.getparent()
                testcase_classname = testcase.get("classname")
                testcase_name = testcase.get("name", "")
                if not testcase_classname:
                    continue
                if testcase_classname.startswith("org.apache.maven.surefire.junit"):
                    testcase_fullname = testcase_name
                else:
                    testcase_fullname = "{}#{}".format(testcase_classname, testcase_name)
                failure_type = element.get("type")
                failure_msg = element.get("message")
                for failure_line in reversed(element.text.splitlines()):
                    if failure_line.strip().startswith("Caused by:"):
                        # Strip "Caused by: " prefix
                        failure_info = failure_line.strip().split(":", maxsplit=1)[-1]
                        failure_info_lst = re.split("[;:]", failure_info, maxsplit=1)
                        if len(failure_info_lst) == 2:
                            failure_type = failure_info_lst[0].strip()
                            failure_msg = failure_info_lst[1].strip()
                            break
                # Retrieve original path for verifying tests
                if original_path and failure_msg:
                    failure_msg = failure_msg.replace(source_path, original_path)

                # Convert None to null for comparison
                if failure_msg is None:
                    failure_msg = "null"

                failed_tests[failure_type].setdefault(failure_msg, set()).add(testcase_fullname)

    logging.info("The total Failures and Errors: {}".format(total_fail))
    logging.info(failed_tests)
    return failed_tests, total_fail


def cleanup(target_dir, source_tempdir):
    # Check existing target_name directory
    if os.path.exists(target_dir):
        logging.warning("Found existing target_name directory: {}".format(target_dir))
        # sys.exit("Please use new target_name or remove old directory!")
        shutil.rmtree(target_dir)
        logging.warning("The old target_name directory has been removed!"
                        " Warning: modify 'remove' to 'exit' for production.")

    # Clear up old temporary base directory in source path
    if os.path.isdir(source_tempdir):
        logging.warning("Cleaning old temporary files created by PExReport: {}".format(source_tempdir))
        shutil.rmtree(source_tempdir)


def copy_internal(needed, source_internal, target_lib_internal, target_lib_class, target_lib_external, source_path,
                  setting):
    miss_JARs = 0
    miss_classes = 0
    if not setting.OPT_debloat:
        for jar in needed.get("internal", {}):
            logging.info("Reducing and packing internal classes...")
            source_jar = os.path.join(source_internal, jar)
            source_unzip = os.path.splitext(source_jar)[0]
            if os.path.isfile(source_jar):
                # Unzip the JAR file
                with zipfile.ZipFile(source_jar) as z:
                    z.extractall(source_unzip)

                if setting.OPT_generated:
                    # Handle processor
                    processors = set()
                    processor_path = os.path.join(source_unzip,
                                                  "META-INF/services/javax.annotation.processing.Processor")
                    if os.path.isfile(processor_path):
                        with open(processor_path, "r") as p:
                            processors = {x.strip() for x in p.readlines() if not x.startswith("#")}

                if setting.OPT_generated and (needed.get("processor", set()) & processors):
                    logging.info("Keep classes for processor: {}".format(processors))
                    pass
                else:
                    if setting.OPT_generated and processors:
                        os.remove(processor_path)
                    logging.info("Remove classes from: {}".format(jar))
                    # Delete class
                    needed_classes = needed.get("internal", {}).get(jar, set())
                    for root, _, files in os.walk(source_unzip):
                        for file in files:
                            if os.path.splitext(file)[1] == ".class":
                                class_path = os.path.join(root, file)[len(source_unzip) + 1:]
                                cls = os.path.splitext(class_path)[0]
                                if not (cls in needed_classes or cls.split("$")[0] in needed_classes):
                                    os.remove(os.path.join(source_unzip, class_path))

                # Pack jar
                cmd = ["jar", "-cf", os.path.join(target_lib_internal, jar), "-C", source_unzip, "."]
                logging.info(" ".join(cmd))
                subprocess.run(cmd)
            else:
                logging.info("Internal JAR is missing: {}".format(jar))
                miss_JARs += 1
                miss_classes += len(needed.get("internal", {}).get(jar, set()))
    else:
        logging.info("Debloating internal classes...")
        cmd = ["tools/proguard-7.2.2/bin/proguard.sh",
               "-dontoptimize", "-dontobfuscate", "-dontwarn",
               "-libraryjars", "<java.home>/lib/rt.jar",
               "-libraryjars", target_lib_external,
               "-injars", os.path.join(source_path, "target/classes"),
               "-injars", os.path.join(source_path, "target/test-classes"),
               "-keep", "class * {*;}",
               "-injars", source_internal,
               "-outjars", target_lib_internal]
        logging.info(" ".join(cmd))
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if setting.OPT_generated:
        # Handle generated classes
        if "generated-classes" in needed:
            source_jar = os.path.join(source_internal, "generated-classes-0.1.jar")
            source_unzip = os.path.splitext(source_jar)[0]
            if os.path.isfile(source_jar) and target_lib_class:
                with zipfile.ZipFile(source_jar) as z:
                    z.extractall(source_unzip)
                for clazz in needed.get("generated-classes", []):
                    class_fname = clazz + ".class"
                    source_fpath = os.path.join(source_unzip, class_fname)
                    if os.path.isfile(source_fpath):
                        target_fpath = os.path.join(target_lib_class, class_fname)
                        os.makedirs(os.path.dirname(target_fpath), exist_ok=True)
                        shutil.copyfile(source_fpath, target_fpath)
                    else:
                        logging.info("Generated class is missing: {}".format(clazz))
                        miss_classes += 1
            else:
                logging.info("Generated classes JAR is missing.")
                miss_JARs += 1
                miss_classes += len(needed.get("generated-classes", []))
    logging.info("# of missing jars: {}".format(miss_JARs))
    logging.info("# of missing internal classes: {}".format(miss_classes))
    return True


def copy_source_to_target(needed, key, source_java_path, target_java_path, source_classes_path, target_class,
                          source_roots, setting):
    miss_count = 0
    for clazz in needed.get(key, []):
        # copy source code
        java_fname = clazz.split("$")[0] + ".java"
        source_fpath = os.path.join(source_java_path, java_fname)
        if os.path.isfile(source_fpath):
            target_fpath = os.path.join(target_java_path, java_fname)
            os.makedirs(os.path.dirname(target_fpath), exist_ok=True)
            shutil.copyfile(source_fpath, target_fpath)
        else:
            logging.info("Source is missing: {}".format(java_fname))
            if setting.OPT_generated:
                locate_source = False
                # Search generated source
                for root in source_roots:
                    source_fpath = os.path.join(root, java_fname)
                    if os.path.isfile(source_fpath):
                        if root.endswith(("/annotations", "/test-annotations")):
                            logging.info("Skip: source is generated from annotation processing: {}".format(java_fname))
                        else:
                            target_fpath = os.path.join(target_java_path, java_fname)
                            os.makedirs(os.path.dirname(target_fpath), exist_ok=True)
                            logging.info("Copy generated source {}".format(source_fpath))
                            shutil.copyfile(source_fpath, target_fpath)
                        locate_source = True
                        break

                # If fail to locate the source, copy class file
                if not locate_source:
                    class_fname = clazz + ".class"
                    source_fpath = os.path.join(source_classes_path, class_fname)
                    if os.path.isfile(source_fpath):
                        logging.info("Copy class: {}".format(class_fname))
                        target_fpath = os.path.join(target_class, class_fname)
                        os.makedirs(os.path.dirname(target_fpath), exist_ok=True)
                        shutil.copyfile(source_fpath, target_fpath)
                    else:
                        logging.info("Class is missing: {}".format(clazz))
                        miss_count += 1
            else:
                miss_count += 1
    return miss_count


def copy_src(needed, source_path, target_path, target_class, setting):
    source_src_main_java_path = os.path.join(source_path, "src/main/java")
    source_src_test_java_path = os.path.join(source_path, "src/test/java")
    target_src_main_java_path = os.path.join(target_path, "src/main/java")
    target_src_test_java_path = os.path.join(target_path, "src/test/java")
    source_classes_path = os.path.join(source_path, "target/classes")
    source_test_classes_path = os.path.join(source_path, "target/test-classes")

    # Source roots for generated source without main and test roots
    compile_source_roots = needed.get("source-roots", {}).get("compile", [])
    try:
        compile_source_roots.remove(source_src_main_java_path)
    except ValueError:
        pass
    test_compile_source_roots = needed.get("source-roots", {}).get("test-compile", [])
    try:
        test_compile_source_roots.remove(source_src_test_java_path)
    except ValueError:
        pass

    miss_count = 0
    miss_count += copy_source_to_target(needed, "classes", source_src_main_java_path, target_src_main_java_path,
                                        source_classes_path, target_class, compile_source_roots, setting=setting)
    # copy test source code
    miss_count += copy_source_to_target(needed, "test-classes", source_src_test_java_path, target_src_test_java_path,
                                        source_test_classes_path, target_class, test_compile_source_roots,
                                        setting=setting)
    logging.info("# of total missing classes: {}".format(miss_count))
    return True


def copy_resource(needed, source_path, target_path):
    # copy files
    ext = ("pom.xml", ".log")
    source_resources_f = [p for p in needed.get("resources-f", set()) if not p.endswith(ext)]
    for source_resource_f in source_resources_f:
        real_source_resource = source_resource_f.replace("/target/classes/", "/src/main/resources/").replace(
            "/target/test-classes/", "/src/test/resources/")
        if os.path.isfile(real_source_resource):
            target_resource = os.path.join(target_path, os.path.relpath(real_source_resource, source_path))
            os.makedirs(os.path.dirname(target_resource), exist_ok=True)
            shutil.copyfile(real_source_resource, target_resource)
        elif os.path.isfile(source_resource_f):
            logging.info("Only find resource in 'target' directory, copy to test resources")
            test_source_resource = real_source_resource.replace("/src/main/resources/", "/src/test/resources/")
            target_resource = os.path.join(target_path, os.path.relpath(test_source_resource, source_path))
            os.makedirs(os.path.dirname(target_resource), exist_ok=True)
            shutil.copyfile(source_resource_f, target_resource)

    # copy directory structure
    for source_resource_d in needed.get("resources-d", set()):
        real_source_resource = source_resource_d.replace("/target/classes", "/src/main/resources").replace(
            "/target/test-classes", "/src/test/resources")
        if os.path.isdir(real_source_resource):
            target_resource_d = os.path.join(target_path, os.path.relpath(real_source_resource, source_path))
            os.makedirs(target_resource_d, exist_ok=True)
            for resource in os.listdir(real_source_resource):
                target_resource_i = os.path.join(target_resource_d, resource)
                if os.path.isdir(os.path.join(real_source_resource, resource)):
                    os.makedirs(target_resource_i, exist_ok=True)
                elif not os.path.exists(target_resource_i):
                    os.mknod(target_resource_i)


def update_pom(target_path, deps_tree, internal_group, target_internal, target_external, target_class, setting):
    target_pom = os.path.join(target_path, "pom.xml")
    logging.info("Updating target pom: {}".format(target_pom))
    logging.info("Parsing dependency tree file: {}".format(deps_tree))

    tree = etree.parse(target_pom, parser=etree.XMLParser(remove_blank_text=True))
    root = tree.getroot()
    xmlns = root.nsmap[None]
    deps_elm = root.find("{{{}}}dependencies".format(xmlns))
    dep_template = (
        "<dependency>"
        "<groupId>{groupId}</groupId>"
        "<artifactId>{artifactId}</artifactId>"
        "<version>{version}</version>"
        "<type>{type}</type>"
        "<scope>system</scope>"
        "{classifier}"
        "<systemPath>${{pom.basedir}}/{system_path}</systemPath>"
        "</dependency>"
    )

    if os.path.isfile(deps_tree) and (os.path.isdir(target_internal) or os.path.isdir(target_external)):
        internal_deps = []
        external_deps = []
        with open(deps_tree, "r") as f:
            lines = f.readlines()
            logging.info("Dependency tree root: {}".format(lines[0].strip()))
            lines = lines[1:]
            deps = [s.split('- ')[1].strip("\n") for s in lines]
            logging.info("number of deps: {}".format(len(deps)))

        if setting.OPT_generated and os.path.exists(target_class):
            deps_elm.append(etree.Comment(" Generated Classes Dependencies "))
            dep_jar = "generated-classes.jar"
            target_class_jar = os.path.join(target_class, dep_jar)
            logging.info("Packing generated classes...")
            cmd = ["jar", "-cf", target_class_jar, "-C", target_class, "."]
            logging.info(" ".join(cmd))
            subprocess.run(cmd)
            relative_target_class_jar = os.path.relpath(target_class_jar, target_path)
            dep_str = dep_template.format(
                groupId=internal_group,
                artifactId="generated-classes",
                version="0.1",
                type="jar",
                classifier="",
                system_path=relative_target_class_jar)
            deps_elm.append(etree.fromstring(dep_str))

        for dep in deps:
            segs = dep.split(":")
            groupId = segs[0]
            artifactId = segs[1]
            dep_type = segs[2]

            if len(segs) == 5:
                version = segs[3]
                # scope = segs[4]
                classifier_str = ""
                dep_file = "{}-{}.{}".format(artifactId, version, dep_type)
            elif len(segs) == 6:
                classifier = segs[3]
                version = segs[4]
                # scope = segs[5]
                if dep_type == "test-jar":
                    classifier_str = ""
                    dep_file = "{}-{}-{}.jar".format(artifactId, version, classifier)
                else:
                    dep_file = "{}-{}-{}.{}".format(artifactId, version, classifier, dep_type)
                    classifier_str = "<classifier>{}</classifier>".format(classifier)
            else:
                logging.error("Cannot analyze dependency: {}".format(segs))
                continue

            if groupId.startswith(internal_group):
                dep_path = os.path.join(target_internal, dep_file)
                deps_list = internal_deps
            else:
                dep_path = os.path.join(target_external, dep_file)
                deps_list = external_deps

            if os.path.isfile(dep_path):
                deps_list.append(
                    dep_template.format(
                        groupId=groupId,
                        artifactId=artifactId,
                        version=version,
                        type=dep_type,
                        classifier=classifier_str,
                        system_path=os.path.relpath(dep_path, target_path)))
            else:
                logging.info("Ignoring: {}".format(dep_file))

        if internal_deps:
            deps_elm.append(etree.Comment(" Internal Dependencies "))
        for dep_str in internal_deps:
            deps_elm.append(etree.fromstring(dep_str))
        if external_deps:
            deps_elm.append(etree.Comment(" External Dependencies "))
        for dep_str in external_deps:
            deps_elm.append(etree.fromstring(dep_str))

    tree.write(target_pom, encoding="utf-8", xml_declaration=True, pretty_print=True)
