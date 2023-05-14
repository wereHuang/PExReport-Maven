# PExReport-Maven
This is a PExReport implementation for Maven build system. For more information, please check the [PExReport website](https://sites.google.com/view/pexreport/home).
## Create a Working Environment
1. Use a Linux machine, the following instructions are verified in `Ubuntu 22.04 LTS` 

2. Install Maven 3 and pip for Python3
   ```
   sudo apt update && sudo apt install maven python3-pip -y
   ```

3. Install Python packages using `requirements.txt`
   ```
   sudo pip install -r requirements.txt
   ```
   Remove `==version` in `requirements.txt` if any package fails to install. pip will install latest package without the version suffix.

4. Install the customized Maven Archetype for PExReport

   Change the working directory to `pexreport-archetype`, then execute:
   ``` 
   mvn clean install
   ```
5. Install Java 8 (required for test)
    ```
    sudo apt install openjdk-8-jdk -y
    ```
## Run a Test for PExReport-Maven
```
python3 per.py -n com.artemis.EntitySystemOptimizerTest#validate_optimized_system_test \
-s ./test/test-project/artemis-build-tools/artemis-weaver \
-g net.onedaybeard \
-t test1
```
## Command Line Usage
```
usage: per.py [-h] -n TEST_NAME -s SOURCE -g GROUPID -t TARGET [-o OUT_DIR]

PExReport-Maven

required arguments:
  -n TEST_NAME, --test_name TEST_NAME
                        test name for reproducing failure
  -s SOURCE, --source SOURCE
                        path of the source project
  -g GROUPID, --groupid GROUPID
                        current group ID for internal classes
  -t TARGET, --target TARGET
                        name of the created failure project

optional arguments:
  -h, --help            show this help message and exit
  
  -o OUT_DIR, --out_dir OUT_DIR
                        the output directory path
```
