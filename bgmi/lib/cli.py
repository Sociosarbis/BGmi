import datetime
import itertools
import os
import re
import string

import bgmi.config
from bgmi.lib.constants import (
    ACTION_ADD,
    ACTION_CAL,
    ACTION_COMPLETE,
    ACTION_CONFIG,
    ACTION_CONFIG_GEN,
    ACTION_DELETE,
    ACTION_DOWNLOAD,
    ACTION_FETCH,
    ACTION_FILTER,
    ACTION_HISTORY,
    ACTION_LIST,
    ACTION_MARK,
    ACTION_SEARCH,
    ACTION_SOURCE,
    ACTION_UPDATE,
    ACTIONS,
    DOWNLOAD_CHOICE_LIST_DICT,
    SPACIAL_APPEND_CHARS,
    SPACIAL_REMOVE_CHARS,
    SUPPORT_WEBSITE,
    actions_and_arguments,
)
from bgmi.lib.controllers import (
    add,
    config,
    delete,
    filter_,
    list_,
    mark,
    search,
    source,
    update,
)
from bgmi.lib.download import download_prepare, get_download_class
from bgmi.lib.fetch import website
from bgmi.lib.models import (
    STATUS_DELETED,
    STATUS_FOLLOWED,
    STATUS_UPDATED,
    Bangumi,
    Filter,
    Followed,
    Subtitle,
)
from bgmi.script import ScriptRunner
from bgmi.utils import (
    COLOR_END,
    GREEN,
    RED,
    YELLOW,
    get_terminal_col,
    logger,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from tornado import template


def source_wrapper(ret):
    result = source(data_source=ret.source)
    globals()["print_{}".format(result["status"])](result["message"])
    return result


def config_wrapper(ret):
    result = config(ret.name, ret.value)
    if (not ret.name) and (not ret.value):
        print(result["message"])
    else:
        globals()["print_{}".format(result["status"])](result["message"])


def search_wrapper(ret):
    result = search(
        keyword=ret.keyword,
        count=ret.count,
        regex=ret.regex_filter,
        dupe=ret.dupe,
        min_episode=ret.min_episode,
        max_episode=ret.max_episode,
    )
    if result["status"] != "success":
        globals()["print_{}".format(result["status"])](result["message"])
    data = result["data"]
    for i in data:
        print_success(i["title"])
    if ret.download:
        download_prepare(data)


def mark_wrapper(ret):
    result = mark(name=ret.name, episode=ret.episode)
    globals()["print_{}".format(result["status"])](result["message"])


def delete_wrapper(ret):
    if ret.clear_all:
        delete("", clear_all=ret.clear_all, batch=ret.batch)
    else:
        for bangumi_name in ret.name:
            result = delete(name=bangumi_name)
            globals()["print_{}".format(result["status"])](result["message"])


def add_wrapper(ret):
    for bangumi_name in ret.name:
        result = add(name=bangumi_name, episode=ret.episode)
        globals()["print_{}".format(result["status"])](result["message"])


def list_wrapper(*args):
    result = list_()
    print(result["message"])


def cal_wrapper(ret):
    force_update = ret.force_update
    today = ret.today
    save = not ret.no_save

    runner = ScriptRunner()
    if ret.download_cover:
        cover = runner.get_download_cover()
    else:
        cover = None

    weekly_list = website.bangumi_calendar(
        force_update=force_update, save=save, cover=cover
    )

    patch_list = runner.get_models_dict()
    for i in patch_list:
        weekly_list[i["update_time"].lower()].append(i)

    def shift(seq, n):
        n %= len(seq)
        return seq[n:] + seq[:n]

    if today:
        weekday_order = (Bangumi.week[datetime.datetime.today().weekday()],)
    else:
        weekday_order = shift(Bangumi.week, datetime.datetime.today().weekday())

    env_columns = 42 if os.environ.get("TRAVIS_CI", False) else get_terminal_col()

    col = 42

    if env_columns < col:
        print_warning("terminal window is too small.")
        env_columns = col

    row = int(env_columns / col if env_columns / col <= 3 else 3)

    def print_line():
        num = col - 3
        split = "-" * num + "   "
        print(split * row)

    for index, weekday in enumerate(weekday_order):
        if weekly_list[weekday.lower()]:
            print(
                "{}{}. {}".format(
                    GREEN,
                    weekday
                    if not today
                    else "Bangumi Schedule for Today (%s)" % weekday,
                    COLOR_END,
                ),
                end="",
            )
            print()
            print_line()
            for i, bangumi in enumerate(weekly_list[weekday.lower()]):
                if (
                    bangumi["status"] in (STATUS_UPDATED, STATUS_FOLLOWED)
                    and "episode" in bangumi
                ):
                    bangumi["name"] = "%s(%d)" % (bangumi["name"], bangumi["episode"])

                half = len(re.findall("[%s]" % string.printable, bangumi["name"]))
                full = len(bangumi["name"]) - half
                space_count = col - 2 - (full * 2 + half)

                for s in SPACIAL_APPEND_CHARS:
                    if s in bangumi["name"]:
                        space_count += bangumi["name"].count(s)

                for s in SPACIAL_REMOVE_CHARS:
                    if s in bangumi["name"]:
                        space_count -= bangumi["name"].count(s)

                if bangumi["status"] == STATUS_FOLLOWED:
                    bangumi["name"] = "{}{}{}".format(
                        YELLOW, bangumi["name"], COLOR_END
                    )

                if bangumi["status"] == STATUS_UPDATED:
                    bangumi["name"] = "{}{}{}".format(GREEN, bangumi["name"], COLOR_END)
                try:
                    print(" " + bangumi["name"], " " * space_count, end="")
                except UnicodeEncodeError:
                    continue

                if (i + 1) % row == 0 or i + 1 == len(weekly_list[weekday.lower()]):
                    print()
            print()


def filter_wrapper(ret):
    result = filter_(
        name=ret.name,
        subtitle=ret.subtitle,
        include=ret.include,
        exclude=ret.exclude,
        regex=ret.regex,
    )
    if "data" not in result:
        globals()["print_{}".format(result["status"])](result["message"])
    else:
        print_info(
            "Usable subtitle group: {}".format(
                ", ".join(result["data"]["subtitle_group"])
            )
        )
        followed_filter_obj = Filter.get(bangumi_name=ret.name)
        print_filter(followed_filter_obj)
    return result["data"]


def update_wrapper(ret):
    update(name=ret.name, download=ret.download, not_ignore=ret.not_ignore)


def download_manager(ret):
    if ret.id:
        # 没有入口..
        download_id = ret.id
        status = ret.status
        if download_id is None or status is None:
            print_error("No id or status specified.")
        # download_obj = NeoDownload.get(_id=download_id)
        # if not download_obj:
        #     print_error('Download object does not exist.')
        # print_info('Download Object <{0} - {1}>, Status: {2}'.format(download_obj.name, download_obj.episode,
        #                                                              download_obj.status))
        # download_obj.status = status
        # download_obj.save()
        print_success(
            "Download status has been marked as {}".format(
                DOWNLOAD_CHOICE_LIST_DICT.get(int(status))
            )
        )
    else:
        status = ret.status
        status = int(status) if status is not None else None
        delegate = get_download_class(instance=False)
        delegate.download_status(status=status)


def fetch_(ret):
    try:
        bangumi_obj = Bangumi.get(name=ret.name)
    except Bangumi.DoesNotExist:
        print_error("Bangumi {} not exist".format(ret.name))
        return

    try:
        Followed.get(bangumi_name=bangumi_obj.name)
    except Followed.DoesNotExist:
        print_error("Bangumi {} is not followed".format(ret.name))
        return

    followed_filter_obj = Filter.get(bangumi_name=ret.name)
    print_filter(followed_filter_obj)

    print_info("Fetch bangumi {} ...".format(bangumi_obj.name))
    _, data = website.get_maximum_episode(
        bangumi_obj, ignore_old_row=False if ret.not_ignore else True
    )

    if not data:
        print_warning("Nothing.")
    for i in data:
        print_success(i["title"])


def complete(ret):
    # coding=utf-8
    """eval "$(bgmi complete)" to complete bgmi in bash"""
    updating_bangumi_names = [
        x["name"] for x in Bangumi.get_updating_bangumi(order=False)
    ]

    all_config = [x for x in bgmi.config.__all__ if not x == "DATA_SOURCE"]

    actions_and_opts = {}
    helper = {}
    for action_dict in actions_and_arguments:
        actions_and_opts[action_dict["action"]] = []
        for arg in action_dict.get("arguments", []):
            if isinstance(arg["dest"], str) and arg["dest"].startswith("-"):
                actions_and_opts[action_dict["action"]].append(arg)
            elif isinstance(arg["dest"], list):
                actions_and_opts[action_dict["action"]].append(arg)
        helper[action_dict["action"]] = action_dict.get("help", "")

    if "bash" in os.getenv("SHELL").lower():  # bash
        template_file_path = os.path.join(
            os.path.dirname(__file__), "..", "others", "_bgmi_completion_bash.sh"
        )

    elif "zsh" in os.getenv("SHELL").lower():  # zsh
        template_file_path = os.path.join(
            os.path.dirname(__file__), "..", "others", "_bgmi_completion_zsh.sh"
        )

    else:
        import sys

        print(
            "unsupported shell {}".format(os.getenv("SHELL").lower()), file=sys.stderr
        )
        return

    with open(template_file_path) as template_file:
        shell_template = template.Template(template_file.read(), autoescape="")

    template_with_content = shell_template.generate(
        actions=ACTIONS,
        bangumi=updating_bangumi_names,
        config=all_config,
        actions_and_opts=actions_and_opts,
        source=[x["id"] for x in SUPPORT_WEBSITE],
        helper=helper,
        isinstance=isinstance,
        string_types=(str,),
    )  # type: bytes

    if os.environ.get("DEBUG", False):  # pragma: no cover
        with open("./_bgmi", "wb+") as template_file:
            template_file.write(template_with_content)

    template_with_content = template_with_content.decode("utf-8")
    print(template_with_content)


def history(ret):
    m = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    data = Followed.select(Followed).order_by(Followed.updated_time.asc())
    bangumi_data = Bangumi.get_updating_bangumi()
    year = None
    month = None

    updating_bangumi = list(
        map(lambda s: s["name"], itertools.chain(*bangumi_data.values()))
    )

    print_info("Bangumi Timeline")
    for i in data:
        if i.status == STATUS_DELETED:
            slogan = "ABANDON"
            color = RED
        else:
            if i.bangumi_name in updating_bangumi:
                slogan = "FOLLOWING"
                color = YELLOW
            else:
                slogan = "FINISHED"
                color = GREEN

        if not i.updated_time:
            date = datetime.datetime.fromtimestamp(0)
        else:
            date = datetime.datetime.fromtimestamp(int(i.updated_time))

        if date.year != 1970:
            if date.year != year:
                print("{}{}{}".format(GREEN, str(date.year), COLOR_END))
                year = date.year

            if date.year == year and date.month != month:
                print(
                    "  |\n  |--- {}{}{}\n  |      |".format(
                        YELLOW, m[date.month - 1], COLOR_END
                    )
                )
                month = date.month

            print(
                "  |      |--- [{}{:<9}{}] ({:<2}) {}".format(
                    color, slogan, COLOR_END, i.episode, i.bangumi_name
                )
            )


def config_gen(ret):
    template_file_path = os.path.join(
        os.path.dirname(__file__), "..", "others", "nginx.conf"
    )

    with open(template_file_path) as template_file:
        shell_template = template.Template(template_file.read(), autoescape="")

    template_with_content = shell_template.generate(
        actions=ACTIONS,
        server_name=ret.server_name,
        os_sep=os.sep,
        front_static_path=bgmi.config.FRONT_STATIC_PATH,
        save_path=bgmi.config.SAVE_PATH,
    )  # type: bytes

    template_with_content = template_with_content.decode("utf-8")
    print(template_with_content)


CONTROLLERS_DICT = {
    ACTION_ADD: add_wrapper,
    ACTION_SOURCE: source_wrapper,
    ACTION_DOWNLOAD: download_manager,
    ACTION_CONFIG: config_wrapper,
    ACTION_DELETE: delete_wrapper,
    ACTION_MARK: mark_wrapper,
    ACTION_SEARCH: search_wrapper,
    ACTION_FILTER: filter_wrapper,
    ACTION_CAL: cal_wrapper,
    ACTION_UPDATE: update_wrapper,
    ACTION_FETCH: fetch_,
    ACTION_LIST: list_wrapper,
    ACTION_COMPLETE: complete,
    ACTION_HISTORY: history,
    ACTION_CONFIG_GEN: config_gen,
}


def controllers(ret):
    logger.info(ret)
    func = CONTROLLERS_DICT.get(ret.action, None)
    if not callable(func):
        return
    else:
        return func(ret)


def print_filter(followed_filter_obj):
    print_info(
        "Followed subtitle group: {}".format(
            ", ".join(
                map(
                    lambda s: s["name"],
                    Subtitle.get_subtitle_by_id(
                        followed_filter_obj.subtitle.split(", ")
                    ),
                )
            )
            if followed_filter_obj.subtitle
            else "None"
        )
    )
    print_info("Include keywords: {}".format(followed_filter_obj.include))
    print_info("Exclude keywords: {}".format(followed_filter_obj.exclude))
    print_info("Regular expression: {}".format(followed_filter_obj.regex))
