import json
import logging
import os
import subprocess
import deps
import utils
from utils import SetEncoder


class Generic:
    def __init__(self, config_dict, out_dir, OPT_hybrid=True, OPT_build=True, OPT_resource=True, OPT_generated=True,
                 OPT_debloat=False):
        out_dir = os.path.abspath(out_dir)
        self.log_path = os.path.join(out_dir, "log", config_dict.get("target_name", "temp") + ".log")
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        logger = logging.getLogger()
        for handler in logger.handlers[:]:  # remove all old handlers
            handler.flush()
            logger.removeHandler(handler)
        logging.basicConfig(filename=self.log_path, level=logging.DEBUG, filemode="w",
                            format="%(levelname)s - %(message)s")

        logging.info("config_dict: ")
        logging.info(config_dict)
        self.test_name = config_dict.get("test_name")
        self.fail_dir = os.path.join(out_dir, "fail-tests", config_dict.get("target_name", "temp"))
        os.makedirs(self.fail_dir, exist_ok=True)

        self.source_path = os.path.abspath(config_dict.get("source_path"))
        logging.info("source_path: " + self.source_path)
        self.group_ID = config_dict.get("group_ID")
        self.target_name = config_dict.get("target_name")
        # Set maven command path to source project path if not specified
        self.mvn_cmd_path = config_dict.get("mvn_cmd_path", self.source_path)
        # Set source package name to group ID if not specified
        self.source_package = config_dict.get("source_package", self.group_ID)
        self.add_test_cmds = config_dict.get("add_test_cmds",
                                             "") + " -Drat.skip=true -Drat.ignoreErrors=true -Dcheckstyle.skip=true"

        # The temporary base directory for PExReport in source path
        self.source_basedir = os.path.join(self.source_path, utils.SOURCE_BASEDIR_NAME)

        target_basedir_name = "generated-test"
        # The parent directory (target_name) of generated test cases
        self.target_name_dir = os.path.join(out_dir, target_basedir_name, self.target_name)

        # Package name for generated PExReport tests
        self.per_package = "pexreport"

        self.POM = "pom.xml"
        self.PER_POM = "per-pom.xml"

        # Experiment setting
        self.OPT_hybrid = OPT_hybrid
        self.OPT_build = OPT_build
        self.OPT_resource = OPT_resource
        self.OPT_generated = OPT_generated
        self.OPT_debloat = OPT_debloat

    def execute_with(self, test_name, per_test_cmds=""):
        if test_name:
            artifactId = test_name.replace("#", "."). \
                replace("[", "_"). \
                replace("]", "_"). \
                replace(" ", "_"). \
                replace("=", "-")
        else:
            artifactId = "All.PExReport"
        source_output_dir = os.path.join(self.source_basedir, artifactId)
        target_path = os.path.join(self.target_name_dir, artifactId)
        full_test_cmds = self.add_test_cmds + " " + per_test_cmds

        logging.info("Creating a temporary base directory for PExReport in source path: {}".format(self.source_basedir))
        os.makedirs(source_output_dir, exist_ok=True)
        logging.info("Creating a target_path directory: {}".format(target_path))
        os.makedirs(target_path, exist_ok=True)
        print(target_path)

        logging.info("Simple run of the source bug...")
        expected_failed_tests, expected_total_fail = utils.simple_run(self.source_path, self.mvn_cmd_path, test_name,
                                                                      full_test_cmds, self.PER_POM)
        if not expected_failed_tests:
            return False

        logging.info("Dependencies analysis...")
        needed = deps.extract_deps(cwd=self.mvn_cmd_path, source_path=self.source_path,
                                   prefix=self.source_package, group_prefix=self.group_ID,
                                   test_name=test_name, add_test_cmds=full_test_cmds, output_dir=source_output_dir,
                                   pom=self.PER_POM, setting=self)
        if not needed:
            return False

        # Change original path to target path
        maven_setting_dict = needed.get("maven-setting", {})
        for key, value in maven_setting_dict.items():
            if self.source_path in value:
                maven_setting_dict[key] = value.replace(self.source_path, "${project.basedir}")

        logging.info("Generating target test project template...")
        cmd = ["mvn", "--quiet", "archetype:generate", "-B", "-DarchetypeGroupId={}".format(self.per_package),
               "-DarchetypeArtifactId=pexreport-archetype", "-DarchetypeVersion=1.0-SNAPSHOT",
               "-DgroupId={}".format(self.per_package), "-Dversion=1.0-SNAPSHOT",
               "-DartifactId={}".format(artifactId),
               "-DmavenCompilerSource={}".format(needed.get("maven-setting", {}).get("maven.compiler.source", "")),
               "-DmavenCompilerTarget={}".format(needed.get("maven-setting", {}).get("maven.compiler.target", "")),
               "-Dplugins={}".format(needed.get("maven-setting", {}).get("plugins", ""))
               ]
        logging.info(" ".join(cmd))
        subprocess.run(cmd, cwd=self.target_name_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The library base directory for PExReport in target path
        target_lib = os.path.join(target_path, utils.TARGET_LIB_NAME)
        target_lib_internal = os.path.join(target_lib, "internal")
        os.makedirs(target_lib_internal, exist_ok=True)
        target_lib_external = os.path.join(target_lib, "external")
        target_lib_class = os.path.join(target_lib, "class")

        if self.OPT_generated:
            logging.info("Compile source code for class copy")
            subprocess.run(["mvn", "-f", self.PER_POM, "clean", "test-compile", "-Dmaven.compiler.failOnError=false",
                            *self.add_test_cmds.split()], cwd=self.mvn_cmd_path, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)

        logging.info("Copying source code...")
        utils.copy_src(needed, self.source_path, target_path, target_lib_class, setting=self)

        logging.info("Copying external dependencies...")
        cmd = ["mvn", "-f", self.PER_POM, "--quiet", "dependency:copy-dependencies", "-Dtest={}".format(test_name),
               "-DexcludeGroupIds={}".format(self.group_ID), *full_test_cmds.split(),
               "-DoutputDirectory={}".format(target_lib_external)]
        logging.info(" ".join(cmd))
        subprocess.run(cmd, cwd=self.mvn_cmd_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        logging.info("Copying internal dependencies...")
        # Copying dependency jars within same group ID...
        source_internal = os.path.join(source_output_dir, "internal-deps")
        os.makedirs(source_internal, exist_ok=True)
        cmd = ["mvn", "-f", self.PER_POM, "--quiet", "dependency:copy-dependencies", "-Dtest={}".format(test_name),
               "-DincludeGroupIds={}".format(self.group_ID), *full_test_cmds.split(),
               "-DoutputDirectory={}".format(source_internal)]
        logging.info(" ".join(cmd))
        subprocess.run(cmd, cwd=self.mvn_cmd_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        utils.copy_internal(needed, source_internal, target_lib_internal, target_lib_class, target_lib_external,
                            self.source_path, setting=self)

        logging.info("Creating dependency tree from source project...")
        deps_tree = os.path.join(source_output_dir, "deps-tree.log")
        subprocess.run(
            ["mvn", "-f", self.PER_POM, "--quiet", "dependency:tree", "-Dtest={}".format(test_name),
             *full_test_cmds.split(), "-DoutputFile={}".format(deps_tree)], cwd=self.mvn_cmd_path,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        logging.info("Updating all dependencies in target pom.xml...")
        utils.update_pom(target_path, deps_tree, self.group_ID, target_lib_internal, target_lib_external,
                         target_lib_class, setting=self)

        if self.OPT_resource:
            logging.info("Copying resources...")
            utils.copy_resource(needed, self.source_path, target_path)
        else:
            logging.info("Copying resources...Skip!")

        logging.info("Verifying generated tests at {}".format(target_path))
        actual_failed_tests, actual_total_fail = utils.simple_run(target_path, target_path, test_name,
                                                                  original_path=self.source_path)

        with open(os.path.join(self.fail_dir, (test_name if test_name else "all") + "-expected.json"), "w") as f:
            json.dump(expected_failed_tests, f, cls=SetEncoder)

        with open(os.path.join(self.fail_dir, (test_name if test_name else "all") + "-actual.json"), "w") as f:
            json.dump(actual_failed_tests, f, cls=SetEncoder)

        if actual_total_fail <= 0:
            logging.error("Verification Failed!")
            return False

        for failed_type in expected_failed_tests:
            if failed_type not in actual_failed_tests:
                logging.error("Verification Failed!")
                return False
            else:
                for failed_message in expected_failed_tests[failed_type]:
                    # 100% similarity
                    if failed_message not in actual_failed_tests[failed_type]:
                        logging.error("Verification Failed!")
                        return False

        logging.info("Verification Passed!")
        return True

    def execute(self):
        utils.setup_pom(self.mvn_cmd_path, os.path.join(self.mvn_cmd_path, self.POM),
                        os.path.join(self.mvn_cmd_path, self.PER_POM))
        # Clear up old temporary directories
        utils.cleanup(self.target_name_dir, self.source_basedir)

        print(f"Creating the pruned failure report for {self.test_name}...")
        return self.execute_with(self.test_name)
