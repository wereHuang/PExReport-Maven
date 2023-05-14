import argparse
import subprocess
from generic import Generic
from report import timer_start, timer_end

parser = argparse.ArgumentParser(description='PExReport-Maven')
parser.add_argument('-n', '--test_name', required=True, help='test name for reproducing failure')
parser.add_argument('-s', '--source', required=True, help='path of the source project')
parser.add_argument('-g', '--groupid', required=True, help='current group ID for internal classes')
parser.add_argument('-t', '--target', required=True, help='name of the created failure project')
parser.add_argument('-o', '--out_dir', default='./out', help='the output directory path')

args = parser.parse_args()
# print(args)

config_dict = {"source_path": args.source, "group_ID": args.groupid, "target_name": args.target,
               "test_name": args.test_name}
timer_start()
try:
    if Generic(config_dict, args.out_dir).execute():
        print("passed. ", end="")
    else:
        print("failed! ", end="")
except subprocess.TimeoutExpired:
    print("timeout! ", end="")
print(f"{timer_end()}Sec")
