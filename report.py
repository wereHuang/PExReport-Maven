import logging
import os
import time
import zipfile

global_time = -1


def timer_start():
    global global_time
    if global_time < 0:
        logging.info("Timer start!")
    else:
        logging.warning("Timer restart!!!")
    global_time = time.perf_counter()
    return round(global_time, 2)


def timer_end():
    global global_time
    if global_time < 0:
        logging.warning("Timer end before start!")
        elapsed_time = -1
    else:
        logging.info("Timer end!")
        elapsed_time = round(time.perf_counter() - global_time, 2)
        logging.info("Elapsed time in seconds: {}".format(elapsed_time))
    logging.info("Reset timer!")
    global_time = -1
    return elapsed_time


def count_class(src_path, internal_path):
    main_cls_set = set()
    test_cls_set = set()
    main_cls_path = os.path.join(src_path, "target/classes")
    test_cls_path = os.path.join(src_path, "target/test-classes")
    internal_cls_set = set()
    internal_fpath = os.path.join(src_path, internal_path)

    for root, _, files in os.walk(main_cls_path):
        for file in files:
            if os.path.splitext(file)[1] == ".class":
                main_cls_set.add(os.path.relpath(os.path.join(root, file), main_cls_path))

    for root, _, files in os.walk(test_cls_path):
        for file in files:
            if os.path.splitext(file)[1] == ".class":
                test_cls_set.add(os.path.relpath(os.path.join(root, file), test_cls_path))

    internal_jar = set([name for name in os.listdir(internal_fpath)
                        if os.path.isfile(os.path.join(internal_fpath, name))
                        and os.path.splitext(name)[1] == ".jar"])
    # remove generated classes from internal jar
    if "generated-classes-0.1.jar" in internal_jar:
        print("Warning: Found generated-classes-0.1.jar!")
        internal_jar.discard("generated-classes-0.1.jar")
    for jar in internal_jar:
        with zipfile.ZipFile(os.path.join(internal_fpath, jar), "r") as jar_zip:
            for name in jar_zip.namelist():
                if os.path.splitext(name)[1] == ".class":
                    internal_cls_set.add(jar + name)
    return main_cls_set | test_cls_set, internal_cls_set


def count_resources(src_path):
    main_res_set = set()
    main_res_path = os.path.join(src_path, "src/main/resources")
    if os.path.exists(main_res_path):
        for root, _, files in os.walk(main_res_path):
            for file in files:
                res_path = os.path.join(root, file)
                if os.stat(res_path).st_size != 0:
                    main_res_set.add(os.path.relpath(res_path, main_res_path))

    test_res_set = set()
    test_res_path = os.path.join(src_path, "src/test/resources")
    if os.path.exists(test_res_path):
        for root, _, files in os.walk(test_res_path):
            for file in files:
                res_path = os.path.join(root, file)
                if os.stat(res_path).st_size != 0:
                    test_res_set.add(os.path.relpath(res_path, test_res_path))
    return main_res_set | test_res_set


def count_config(config_path):
    # return sum(1 for _ in open(config_path, "r"))]
    count = 0
    dep_flag = False
    with open(config_path, "r") as f:
        for line in f:
            s = line.strip()
            if s == "<dependencies>":
                dep_flag = True
                continue
            elif s == "</dependencies>":
                dep_flag = False
                continue
            if not dep_flag:
                count += sum(list(map(len, s.split())))

    return count


def stat_source(source_path, cmd_path):
    res = {}
    per_temp_path = os.path.join(source_path, "pexreport-temp")
    tests_dir_lst = [x for x in os.listdir(per_temp_path) if not x.startswith(".")]
    if len(tests_dir_lst) == 0:
        print("Warning: Cannot find the tests dir in source path!")
        return {}
    for test_dir in tests_dir_lst:
        internal_deps_path = os.path.join(per_temp_path, test_dir, "internal-deps")
        if os.path.exists(internal_deps_path):
            res["source"] = count_class(source_path, internal_deps_path)
            res["resources"] = count_resources(source_path)
            config = "effective-pom.xml"
            config_path = os.path.join(source_path, config)
            if not os.path.exists(config_path):
                config_path = os.path.join(cmd_path, config)
                if not os.path.exists(config_path):
                    print("Warning: Cannot find {}".format(config_path))
                    res["config"] = -1
                    break
            res["config"] = count_config(config_path)
            break
    return res


def stat_target(target_name_dir, rep_tests):
    res = {}
    if rep_tests is None:
        print("Warning: Cannot find rep tests!")
    else:
        res["target-reps"] = []
        res["target-reps-times"] = []
        res["target-reps-resources"] = []
        res["target-reps-configs"] = []
        for rep_test, rep_test_data in rep_tests.items():
            if rep_test_data[3] != "pass":
                print("Fail to reproduce: ", rep_test)
                res["target-reps"].append((-1, -1))
                res["target-reps-times"].append(rep_test_data[4])
                # res["target-reps-times"].append(-1)
                res["target-reps-resources"].append(-1)
                res["target-reps-configs"].append(-1)
            else:
                rep_test_name = rep_test.replace("#", "."). \
                    replace("[", "_"). \
                    replace("]", "_"). \
                    replace(" ", "_"). \
                    replace("=", "-")
                target_path = os.path.join(target_name_dir, rep_test_name)
                if os.path.exists(target_path):
                    res["target-reps"].append(count_class(target_path, "pexreport-lib/internal"))
                    res["target-reps-times"].append(rep_test_data[4])
                    res["target-reps-resources"].append(count_resources(target_path))
                    config_path = os.path.join(target_path, "pom.xml")
                    if not os.path.exists(config_path):
                        print("Warning: Cannot find {}".format(config_path))
                        res["target-reps-configs"].append(-1)
                    else:
                        res["target-reps-configs"].append(count_config(config_path))
                else:
                    print("Warning: Path not found", target_path)
    return res


def count_cls_size(src_path, internal_path):
    main_cls_list = []
    test_cls_list = []
    main_cls_path = os.path.join(src_path, "target/classes")
    test_cls_path = os.path.join(src_path, "target/test-classes")
    internal_fpath = os.path.join(src_path, internal_path)

    for root, _, files in os.walk(main_cls_path):
        for file in files:
            if os.path.splitext(file)[1] == ".class":
                main_cls_list.append(os.path.getsize(os.path.join(root, file)))

    for root, _, files in os.walk(test_cls_path):
        for file in files:
            if os.path.splitext(file)[1] == ".class":
                test_cls_list.append(os.path.getsize(os.path.join(root, file)))

    internal_jar = set([name for name in os.listdir(internal_fpath)
                        if os.path.isfile(os.path.join(internal_fpath, name))
                        and os.path.splitext(name)[1] == ".jar"])
    # remove generated classes from internal jar
    if "generated-classes-0.1.jar" in internal_jar:
        print("Warning: Found generated-classes-0.1.jar!")
        internal_jar.discard("generated-classes-0.1.jar")
    return sum(main_cls_list + test_cls_list), sum(
        [os.path.getsize(os.path.join(internal_fpath, jar)) for jar in internal_jar])


def cls_size_source(source_path):
    res = {}
    per_temp_path = os.path.join(source_path, "pexreport-temp")
    tests_dir_lst = [x for x in os.listdir(per_temp_path) if not x.startswith(".")]
    if len(tests_dir_lst) == 0:
        print("Warning: Cannot find the tests dir in source path!")
        return {}
    for test_dir in tests_dir_lst:
        internal_deps_path = os.path.join(per_temp_path, test_dir, "internal-deps")
        if os.path.exists(internal_deps_path):
            res["source"] = count_cls_size(source_path, internal_deps_path)
            break
    return res


def cls_size_target(target_name_dir, rep_tests):
    res = {}
    if rep_tests is None:
        print("Warning: Cannot find rep tests!")
    else:
        res["target-reps"] = []
        for rep_test, rep_test_data in rep_tests.items():
            if rep_test_data[3] != "pass":
                print("Fail to reproduce: ", rep_test)
                res["target-reps"].append((-1, -1))
            else:
                rep_test_name = rep_test.replace("#", "."). \
                    replace("[", "_"). \
                    replace("]", "_"). \
                    replace(" ", "_"). \
                    replace("=", "-")
                target_path = os.path.join(target_name_dir, rep_test_name)
                if os.path.exists(target_path):
                    res["target-reps"].append(count_cls_size(target_path, "pexreport-lib/internal"))
                else:
                    print("Warning: Path not found", target_path)
    return res
