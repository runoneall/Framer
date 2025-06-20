import argparse
import os
import sys
import time
import subprocess
import functools
import random
import urllib.request
import zipfile

# import helper
from . import helper

# python executable
python = sys.executable

# framer repo
framer_repo = "https://github.com/FramerOrg/Framer.git"

# CLI init
logger = functools.partial(helper.logger, "CLI")
sys.excepthook = helper.global_except_hook

# init runner config
runner_config = {
    "exit_on_finish": False,
    "restart_on_error": False,
    "restart_sleep": 1,
    "restart_on_file_change": False,
}

# init install config
install_config = {
    "overwrite": False,
}


# parser class
class LoggerParser(argparse.ArgumentParser):
    def error(self, message):
        logger(message)
        sys.exit(1)


# actions
class ShowHelpAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger(parser.format_help())


class OpenShellAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        while True:
            command = input("Framer> ")
            if command.lower() == "exit":
                break
            try:
                main_parser.parse_args(command.split())
            except:
                pass


class TestFramerAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger("Testing Framer...")
        self.generate_test_file()

        try:
            os.system(f"{python} {self.test_file}")
        finally:
            if os.path.exists(self.test_file):
                os.remove(self.test_file)

    def generate_test_file(self):
        test_file = (
            "test_framer_"
            + "".join(
                random.sample(
                    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", 10
                )
            )
            + ".py"
        )
        helper.write_file(
            test_file,
            """import Framer
Framer.init(link_to=__name__, log_name="CLI", hook_error=True)
logger("Hello Framer!")""",
        )
        self.test_file = test_file
        logger(f"Create {test_file}")


class InitProjectAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger("Init Project...")
        if helper.no_framerpkg():
            helper.write_file(
                "./framerpkg.json",
                helper.json_dump(
                    {
                        "modules": [],
                        "disable": [],
                        "origins": [],
                    }
                ),
            )
        if helper.no_framer_modules():
            helper.clean_dir("./framer_modules")
        logger("Init Project Done")


class ModuleCLIAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        module = values[0]
        args = values[1:]
        installed_modules = helper.load_installed_modules()

        # if module not installed
        if module not in installed_modules:
            raise ImportError(f"Module {module} not installed")

        # import module
        sys.path.append("./framer_modules")
        module_obj = __import__(module)

        # if no entry point
        if not hasattr(module_obj, "cliMain"):
            raise ImportError(f"Module {module} has no Entry Point: cliMain")

        # run entry point
        module_obj.cliMain(args)


class FramerUpdateAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger("Update Framer...")
        helper.clean_dir("update_tmp")
        fetch_status = self.exec_command("git clone {} update_tmp".format(framer_repo))
        if fetch_status != 0:
            logger("Fetch Framer Failed")
            helper.clean_dir("update_tmp", remove=True)
            return
        helper.clean_dir("Framer", remove=True)
        os.rename("update_tmp", "Framer")
        logger("Update Framer Done")

    def exec_command(self, command):
        return os.system(command)


class EnvInitAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger("Init Env File...")
        if helper.no_env():
            helper.write_file("env.json", "{}")
        logger("Init Env File Done")


class EnvListAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        env = helper.load_env()
        logger(
            "Env Links: \n- {}".format(
                "\n- ".join([f"{key} => {value}" for key, value in env.items()])
            )
        )


class EnvSetAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        key = values[0]
        value = self.parse_env_value(values[1])
        if helper.no_env():
            logger("No Env File, Use --init First")
            return
        env = helper.load_env()

        # write env file
        logger(f"Set Env {key} => {value}")
        env[key] = value
        helper.write_file("env.json", helper.json_dump(env))

    def parse_env_value(self, value):
        if ":" not in value:
            return value
        else:
            value_type, value = value.split(":", 1)
            if value_type == "str":
                return value
            elif value_type == "int":
                return int(value)
            elif value_type == "float":
                return float(value)
            elif value_type == "bool":
                return value.lower() == "true"
            else:
                logger(f"Invalid value type: {value_type}")
                return f"{value_type}:{value}"


class EnvDelAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        key = values[0]
        env = helper.load_env()

        # write env file
        logger(f"Delete Env {key}")
        if key in env:
            del env[key]
        helper.write_file("env.json", helper.json_dump(env))


class RunnerConfigAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if option_string == "--exit-on-finish":
            runner_config["exit_on_finish"] = True
        if option_string == "--restart-on-error":
            runner_config["restart_on_error"] = True
        if option_string == "--restart-sleep":
            runner_config["restart_sleep"] = int(values[0])
        if option_string == "--restart-on-file-change":
            runner_config["restart_on_file_change"] = True


class RunnerStartAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        logger("Start Runner...")
        command = [python] + values
        self.file_watchs = []
        if runner_config["restart_on_file_change"] == True:
            logger("Get File Watch List...")
            self.get_watch_list()
            logger("Watch List: \n- {}".format("\n- ".join(self.file_watchs)))

        # run command
        self.process = subprocess.Popen(command)

        # process manage
        try:
            while True:

                # check file change
                if self.check_file_change() == True:
                    if runner_config["restart_on_file_change"] == True:
                        self.stop_runner()
                        self.sleep()
                        self.process = subprocess.Popen(command)

                if self.process.poll() != None:

                    # script run finish
                    if self.process.returncode == 0:
                        if runner_config["exit_on_finish"] == True:
                            break
                        else:
                            logger(
                                "Runner Exit {}, Wait Next Event...".format(
                                    self.process.returncode
                                )
                            )
                            self.sleep()

                    # script run error
                    if self.process.returncode != 0:
                        if runner_config["restart_on_error"] == True:
                            logger(
                                "Runner Exit {}, Restart".format(
                                    self.process.returncode
                                )
                            )
                            self.sleep()
                            self.process = subprocess.Popen(command)
                        else:
                            break

        # runner exit
        except KeyboardInterrupt:
            logger("KeyboardInterrupt, Stop Runner...")
            self.stop_runner()
        finally:
            logger("Runner Exit {}".format(self.process.returncode))

    def get_watch_list(self):
        self.file_watchs += [
            f"./{fname}"
            for fname in os.listdir(".")
            if not fname.startswith(".")
            and fname.endswith(".py")
            and os.path.isfile(f"./{fname}")
        ]
        for fbase, _, fnames in os.walk("./framer_modules"):
            self.file_watchs += [
                f"{fbase}/{fname}"
                for fname in fnames
                if not fname.startswith(".")
                and fname.endswith(".py")
                and os.path.isfile(f"{fbase}/{fname}")
            ]
        self.modified_time = {}
        for fname in self.file_watchs:
            self.modified_time[fname] = os.path.getmtime(fname)

    def check_file_change(self):
        for fname in self.file_watchs:
            if os.path.getmtime(fname) != self.modified_time[fname]:
                self.modified_time[fname] = os.path.getmtime(fname)
                logger(f"File {fname} Changed, Restart")
                return True
        return False

    def sleep(self):
        time.sleep(runner_config["restart_sleep"])

    def stop_runner(self):
        try:
            self.process.terminate()
            self.process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class OriginAddAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):

        # origin url
        origin = values[0]
        logger(f"Add {origin}")

        # load framerpkg
        if helper.no_framerpkg():
            main_parser.parse_args(["--init"])
        framerpkg = helper.load_framerpkg()

        # add origin
        if origin not in framerpkg["origins"]:
            framerpkg["origins"].append(origin)
            helper.write_file("./framerpkg.json", helper.json_dump(framerpkg))
        logger(f"Add Done")


class OriginDelAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        origin = values[0]
        logger(f"Delete {origin}")

        # load framerpkg
        if helper.no_framerpkg():
            main_parser.parse_args(["--init"])
        framerpkg = helper.load_framerpkg()

        # delete origin
        if origin in framerpkg["origins"]:
            framerpkg["origins"].remove(origin)
            helper.write_file("./framerpkg.json", helper.json_dump(framerpkg))
        logger(f"Delete Done")


class OriginListAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        framerpkg = helper.load_framerpkg()
        logger("Origins: \n- {}".format("\n- ".join(framerpkg["origins"])))


class OriginSyncAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        framerpkg = helper.load_framerpkg()
        origin_module_cache = {}

        # fetch origins
        for origin_url in framerpkg["origins"]:
            origin_map = helper.json_load(self.http_text_get(f"{origin_url}/map.json"))
            origin_modules = origin_map["modules"]

            # fetch modules
            for module_name in origin_modules:

                # get module info
                module_info = helper.json_load(
                    self.http_text_get(f"{origin_url}/{module_name}/info.json")
                )

                # make new module name
                local_module_name = "{}@{}".format(module_name, origin_map["name"])

                # fetch require
                require = helper.json_load(
                    self.http_text_get(f"{origin_url}/{module_name}/require.json")
                )

                # save module map
                origin_module_cache[local_module_name] = {
                    **module_info,
                    "download": f"{origin_url}/{module_name}/file.zip",
                    "require": require,
                }

        # save sync result
        helper.write_file("./origin-cache.json", helper.json_dump(origin_module_cache))
        logger("Sync Done")

    def http_text_get(self, url, retry=3):
        logger(f"Fetch {url}")
        while retry > 0:
            try:
                response = urllib.request.urlopen(
                    urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "Framer-CLI/1.0 (Official)",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache",
                        },
                    )
                )
                return response.read().decode("utf-8")
            except KeyboardInterrupt:
                logger("KeyboardInterrupt, Stop Fetch...")
                return None
            except Exception:
                logger(f"Fetch {url} Failed, Retry {retry}...")
                retry -= 1
        logger(f"Fetch {url} Failed")
        return None


class OriginMakeAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):

        # init maker dir
        base_dir = "./maker_release"
        helper.clean_dir(base_dir)
        sys.path.append("./framer_modules")

        # load target modules
        modules = helper.load_installed_modules()
        logger("Target To Make: \n- {}".format("\n- ".join(modules)))

        # load maker config
        if not os.path.exists("./origin-maker.json"):
            maker_config = {
                "name": input("Enter Name: "),
                "base": input("Enter Base URL: "),
            }
            helper.write_file("./origin-maker.json", helper.json_dump(maker_config))
        maker_config = helper.json_load(helper.read_file("./origin-maker.json"))
        logger(
            "Maker Config: \n- {}".format(
                "\n- ".join([f"{key}: {value}" for key, value in maker_config.items()])
            )
        )

        # make origin map
        origin_map = helper.json_dump({**maker_config, "modules": modules})
        helper.write_file(f"{base_dir}/map.json", origin_map)
        logger(f"Make Origin Map: \n{origin_map}")

        # process modules
        for module_name in modules:
            logger(f"Process Module {module_name}")

            # get module info
            moduleInfo = __import__(module_name).moduleInfo

            # make module dir
            module_base = f"{base_dir}/{module_name}"
            helper.clean_dir(module_base)

            # write module info
            json_module_info = helper.json_dump(moduleInfo)
            helper.write_file(f"{module_base}/info.json", json_module_info)
            logger("Module {} Info: \n{}".format(module_name, json_module_info))

            # copy version require
            require = helper.json_dump(helper.load_require(module_name))
            helper.write_file(
                f"{module_base}/require.json",
                require,
            )
            logger("Copy Module {} Require: \n{}".format(module_name, require))

            # zip module
            zip_from = f"./framer_modules/{module_name}"
            zip_to = f"{module_base}/file.zip"
            self.create_zip(
                source_dir=zip_from,
                zip_path=zip_to,
                exclude_dirs=["__pycache__"],
                exclude_files_startswith=["."],
                exclude_hidden=True,
            )

    def create_zip(
        self,
        source_dir,
        zip_path,
        exclude_dirs=None,
        exclude_files_startswith=None,
        exclude_hidden=True,
        compression=zipfile.ZIP_DEFLATED,
    ):
        # init exclude
        exclude_dirs = exclude_dirs or []
        exclude_files_startswith = exclude_files_startswith or []

        # check target dir
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", compression) as zf:
            for root, dirs, files in os.walk(source_dir):
                # process exclude dirs
                dirs[:] = [
                    d
                    for d in dirs
                    if not (
                        (exclude_hidden and d.startswith("."))  # exclude hidden dir
                        or (d in exclude_dirs)  # user specified exclude dir
                    )
                ]

                # process exclude files
                for file in files:
                    if (exclude_hidden and file.startswith(".")) or any(
                        file.startswith(p) for p in exclude_files_startswith
                    ):
                        continue

                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, source_dir)
                    zf.write(file_path, arcname)


class ModuleListAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        modules = helper.load_installed_modules()
        logger("Installed Modules: \n- {}".format("\n- ".join(modules)))


class SyncPackageAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):

        # load installed modules
        modules = helper.load_installed_modules()
        logger("Sync Modules To Framerpkg...")

        # load framerpkg
        if helper.no_framerpkg():
            main_parser.parse_args(["--init"])
        framerpkg = helper.load_framerpkg()

        # add modules
        framerpkg["modules"] = modules
        helper.write_file("./framerpkg.json", helper.json_dump(framerpkg))
        logger("Sync Done")


class ModuleInfoAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        sys.path.append("./framer_modules")
        module_name = values[0]
        module_info = __import__(module_name).moduleInfo
        logger(f"Module {module_name} Info: \n{helper.json_dump(module_info)}")


class ModuleEnableAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        module_name = values[0]
        framerpkg = helper.load_framerpkg()
        if module_name in framerpkg["disable"]:
            framerpkg["disable"].remove(module_name)
            helper.write_file("./framerpkg.json", helper.json_dump(framerpkg))
        logger(f"Enable Module {module_name}")


class ModuleDisableAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        module_name = values[0]
        framerpkg = helper.load_framerpkg()
        if module_name not in framerpkg["disable"]:
            framerpkg["disable"].append(module_name)
            helper.write_file("./framerpkg.json", helper.json_dump(framerpkg))
        logger(f"Disable Module {module_name}")


class ModuleDelAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        module_name = values[0]
        logger(f"Delete Module {module_name}...")
        modules = helper.load_installed_modules()
        if module_name in modules:
            helper.clean_dir(f"./framer_modules/{module_name}", remove=True)
        main_parser.parse_args(["module", "--sync-pkg"])
        logger(f"Delete Done")


class ModuleSearchAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        result = self.search(helper.load_origin_cache(), values[0])

        # show result
        if len(result) > 0:
            logger("Search Result: \n- {}".format("\n- ".join(result)))
        else:
            logger("Search Result: No Match")

    @staticmethod
    def search(module_cache, keyword):

        # sync module
        if helper.no_origin_cache():
            main_parser.parse_args(["origin", "--sync"])

        # get module provider
        provider = ""
        if "@" in keyword:
            keyword, provider = keyword.split("@", 1)

        # get module list
        module_list = list(module_cache.keys())

        # search module
        result = []
        for m in module_list:
            m_keyword, m_provider = m.split("@", 1)
            if keyword.lower() in m_keyword.lower() and m not in result:
                if provider == "":
                    result.append(m)
                if provider != "" and provider.lower() in m_provider.lower():
                    result.append(m)
        return result


class ModuleInstallConfigAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if option_string == "--overwrite":
            install_config["overwrite"] = True


class ModuleInstallAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        module_name = values[0]
        module_cache = helper.load_origin_cache()
        installed_modules = helper.load_installed_modules()
        search_list = ModuleSearchAction.search(module_cache, module_name)

        # get target install
        target_install = ""
        if len(search_list) == 0:
            logger(f"Module {module_name} Not Found")
            return
        if len(search_list) > 1:
            logger(
                "Module {} Found: \n- {}".format(module_name, "\n- ".join(search_list))
            )
            target_install = input("Install: ")
        if target_install == "":
            target_install = search_list[0]
        target_install_name = target_install.split("@")[0]
        logger(f"Install Module {target_install}...")

        # check module exist
        if (
            target_install_name in installed_modules
            and install_config["overwrite"] == False
        ):
            logger("Module Already Installed, Use --overwrite To Reinstall")
            return

        # make install dir
        m_name = target_install.split("@")[0]
        helper.clean_dir("./framer_download_cache")

        # get file
        status = self.http_file_get(
            module_cache[target_install]["download"],
            "./framer_download_cache/file.zip",
        )
        if status == False:
            helper.clean_dir("./framer_download_cache", remove=True)
            return

        # extract file
        helper.clean_dir(f"./framer_modules/{m_name}")
        with zipfile.ZipFile("./framer_download_cache/file.zip", "r") as zf:
            zf.extractall(f"./framer_modules/{m_name}")

        # remove cache
        helper.clean_dir("./framer_download_cache", remove=True)

        # add to framerpkg
        main_parser.parse_args(["module", "--sync-pkg"])

        # scan dependencies
        require = module_cache[target_install]["require"]["dependencies"]
        for r in require:
            main_parser.parse_args(["module", "--install", r])
        logger(f"Install Done")

    def http_file_get(self, url: str, save_to: str, retry=3) -> bool:
        logger(f"Fetch {url}")
        while retry > 0:
            try:
                response = urllib.request.urlopen(
                    urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "Framer-CLI/1.0 (Official)",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache",
                        },
                    )
                )
                with open(save_to, "wb") as f:
                    f.write(response.read())
                return True
            except KeyboardInterrupt:
                logger("KeyboardInterrupt, Stop Fetch...")
                return False
            except Exception:
                logger(f"Fetch {url} Failed, Retry {retry}...")
                retry -= 1
        logger(f"Fetch {url} Failed")
        return False


class ModuleSyncBackAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        framerpkg = helper.load_framerpkg()
        module_list = framerpkg["modules"]

        # check framer_modules
        if helper.no_framer_modules():
            helper.clean_dir("./framer_modules")

        # sync origin cache
        main_parser.parse_args(["origin", "--sync"])

        # install modules
        for module_name in module_list:
            main_parser.parse_args(["module", "--install", module_name])


class ModuleCreateAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):

        # init module dir
        name = values[0]
        logger(f"Create Module {name}...")
        installed_modules = helper.load_installed_modules()
        if name in installed_modules:
            logger(f"Module {name} Already Exists")
            return
        helper.clean_dir(f"./framer_modules/{name}")

        # create __init__.py
        helper.write_file(
            f"./framer_modules/{name}/__init__.py",
            """moduleInfo = {
    "author": "your name",
    "description": "your description here",
    "hooker": False,
}

from .module import moduleMain
""",
        )

        # create module.py
        helper.write_file(
            f"./framer_modules/{name}/module.py",
            """class moduleMain:
    def __init__(self, framer, logger):
        self.framer = framer
        self.logger = logger
""",
        )

        # create require.json
        helper.write_file(
            f"./framer_modules/{name}/require.json",
            helper.json_dump(
                {"dependencies": [], "option_dependencies": [], "pip_dependencies": []}
            ),
        )

        # add to framerpkg
        main_parser.parse_args(["module", "--sync-pkg"])
        logger(f"Create Done")


# parsers
main_parser = LoggerParser(description="Framer CLI", add_help=False)
main_parser.add_argument(
    "-h", "--help", help="Show Help", action=ShowHelpAction, nargs=0
)
main_parser.add_argument(
    "-v", "--version", help="Show Version", action="version", version="1.0 (Official)"
)
main_parser.add_argument(
    "--shell", help="Open Framer Shell", action=OpenShellAction, nargs=0
)
main_parser.add_argument(
    "-t", "--test", help="Test Framer", action=TestFramerAction, nargs=0
)
main_parser.add_argument(
    "--init", help="Init Project", action=InitProjectAction, nargs=0
)
main_parser.add_argument(
    "-m",
    "--module",
    help="Load Module CLI",
    action=ModuleCLIAction,
    nargs=argparse.REMAINDER,
)
main_parser.add_argument(
    "--update", help="Update Framer", action=FramerUpdateAction, nargs=0
)
env_parser = LoggerParser(prog="env", description="Framer CLI", add_help=False)
env_parser.add_argument(
    "-h", "--help", help="Show Help", action=ShowHelpAction, nargs=0
)
env_parser.add_argument("--init", help="Init Env File", action=EnvInitAction, nargs=0)
env_parser.add_argument(
    "-l", "--list", help="List Environments", action=EnvListAction, nargs=0
)
env_parser.add_argument(
    "--set",
    help="Set Environment, TYPE can be 'str', 'int', 'float', 'bool', Default 'str'",
    action=EnvSetAction,
    nargs=2,
    metavar=("KEY", "[TYPE:]VALUE"),
)
env_parser.add_argument(
    "--del",
    help="Delete Environment",
    action=EnvDelAction,
    nargs=1,
    metavar="KEY",
)
runner_parser = LoggerParser(prog="runner", description="Framer CLI", add_help=False)
runner_parser.add_argument(
    "-h", "--help", help="Show Help", action=ShowHelpAction, nargs=0
)
runner_parser.add_argument(
    "--exit-on-finish",
    help="Exit on Finish",
    action=RunnerConfigAction,
    nargs=0,
)
runner_parser.add_argument(
    "--restart-on-error",
    help="Restart on Error",
    action=RunnerConfigAction,
    nargs=0,
)
runner_parser.add_argument(
    "--restart-sleep",
    help="Restart Sleep Seconds",
    action=RunnerConfigAction,
    nargs=1,
    metavar="SECONDS",
)
runner_parser.add_argument(
    "--restart-on-file-change",
    help="Restart on File Change",
    action=RunnerConfigAction,
    nargs=0,
)
runner_parser.add_argument(
    "--start",
    help="Start Runner",
    action=RunnerStartAction,
    nargs=argparse.REMAINDER,
)
origin_parser = LoggerParser(prog="origin", description="Framer CLI", add_help=False)
origin_parser.add_argument(
    "-h", "--help", help="Show Help", action=ShowHelpAction, nargs=0
)
origin_parser.add_argument(
    "--add", help="Add Origin", action=OriginAddAction, nargs=1, metavar="ORIGIN"
)
origin_parser.add_argument(
    "-l", "--list", help="List Origins", action=OriginListAction, nargs=0
)
origin_parser.add_argument(
    "--del", help="Delete Origin", action=OriginDelAction, nargs=1, metavar="ORIGIN"
)
origin_parser.add_argument(
    "--sync", help="Sync Origin", action=OriginSyncAction, nargs=0
)
origin_parser.add_argument(
    "--make", help="Make Origin", action=OriginMakeAction, nargs=0
)
module_parser = LoggerParser(prog="module", description="Framer CLI", add_help=False)
module_parser.add_argument(
    "-h", "--help", help="Show Help", action=ShowHelpAction, nargs=0
)
module_parser.add_argument(
    "-l", "--list", help="List Modules", action=ModuleListAction, nargs=0
)
module_parser.add_argument(
    "--sync-pkg",
    help="Sync Installed Package To Framerpkg",
    action=SyncPackageAction,
    nargs=0,
)
module_parser.add_argument(
    "--info",
    help="Show Module Info",
    action=ModuleInfoAction,
    nargs=1,
    metavar="MODULE",
)
module_parser.add_argument(
    "--enable",
    help="Enable Module",
    action=ModuleEnableAction,
    nargs=1,
    metavar="MODULE",
)
module_parser.add_argument(
    "--disable",
    help="Disable Module",
    action=ModuleDisableAction,
    nargs=1,
    metavar="MODULE",
)
module_parser.add_argument(
    "--del",
    help="Delete Module",
    action=ModuleDelAction,
    nargs=1,
    metavar="MODULE",
)
module_parser.add_argument(
    "-s",
    "--search",
    help="Search Module",
    action=ModuleSearchAction,
    nargs=1,
    metavar="KEYWORD",
)
module_parser.add_argument(
    "--overwrite",
    help="Install Module and Override Old",
    action=ModuleInstallConfigAction,
    nargs=0,
)
module_parser.add_argument(
    "-i",
    "--install",
    help="Install Module",
    action=ModuleInstallAction,
    nargs=1,
    metavar="MODULE",
)
module_parser.add_argument(
    "--sync-back", help="Sync Package Back", action=ModuleSyncBackAction, nargs=0
)
module_parser.add_argument(
    "--create",
    help="Create Empty Framer Modules",
    action=ModuleCreateAction,
    nargs=1,
    metavar="NAME",
)
main_subparsers = main_parser.add_subparsers(dest="subparsers")
main_subparsers.add_parser("env", parents=[env_parser], add_help=False)
main_subparsers.add_parser("runner", parents=[runner_parser], add_help=False)
main_subparsers.add_parser("origin", parents=[origin_parser], add_help=False)
main_subparsers.add_parser("module", parents=[module_parser], add_help=False)


# show help if no arguments
if len(sys.argv) == 1:
    main_parser.parse_args(["--help"])

# parse arguments
else:
    main_parser.parse_args()
