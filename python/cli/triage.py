# Copyright (C) 2020 Hatching B.V.
# All rights reserved.

import sys
import os
import time

import click
import appdirs

from triage import Client
from cli.tui import prompt_select_options

def token_file():
    return os.path.join(appdirs.user_config_dir(), "triage.conf")

def client_from_env():
    tokenfile = token_file()
    if not os.path.exists(tokenfile):
        print("Please authenticate")
        sys.exit()
        return

    with open(token_file(), "r") as f:
        for line in f:
            line = line.strip()
            if len(line) == 0 or line.startswith("#"):
                continue

            url, token = line.split(" ")
            return Client(token, root_url=url)

    print("%s is not formatted correctly" % tokenfile)
    sys.exit()

@click.group()
def cli():
    pass

@cli.command()
@click.argument("token")
@click.option("-u", "--url", default="https://api.tria.ge", help="The endpoint of your triage instance")
def authenticate(token, url):
    tokenfile = token_file()
    if os.path.exists(tokenfile):
        print("Tokenfile already exists, currenty appending tokens is not "
            "supported, please edit/remove: ", tokenfile)
        return

    with open(token_file(), "w") as f:
        f.write("%s %s" % (url, token))

def prompt_select_files(static):
    print("Please select the files from the archive to analyize/")
    print("Leave blank to continue with the emphasized files and automatic "
        "profiles.")

    selection = prompt_select_options(static["files"], key="filename")
    if len(selection) == 0:
        print("Using default selection")
        return [x["relpath"] for x in static["files"] if x["selected"]], True
    return [static["files"][i].get("relpath") for i in selection], False

def prompt_select_profiles_for_files(profiles, pick):
    rt = []
    for i in pick:
        print("Please select the profiles to use for ", i)
        selection = prompt_select_options(profiles, key="name")
        for choice in selection:
            rt.append({
                "profile": profiles[choice]["id"],
                "pick": i
            })
    return rt

def prompt_select_profile(c, sample):
    for events in c.sample_events(sample):
        if events["status"] == "pending":
            print("waiting for static analysis to finish")
        elif events["status"] == "static_analysis":
            break
        elif events["status"] == "failed":
            print("the sample is in a failed state")
            return
        else:
            print("the sample does not need a profile to be selected")
            return
    static = c.static_report(sample)
    if len(static["files"]) >= 1:
        pick, defaultSelection = prompt_select_files(static)

    # Fetch profiles before determining whether we should use automatic
	#  profiles. If no profiles are available, fall back to automatic profiles.
    profiles = [x for x in c.profiles()]
    if defaultSelection or len(profiles) == 0:
        if len(profiles) == 0:
            print("No profiles are available, using automatic profiles "
                "instead.")
        c.set_sample_profile_automatically(sample, pick=pick)
        return

    profile_selections = prompt_select_profiles_for_files(profiles, pick)
    if len(profile_selections) == 0:
        print("Skipping profile selection.. choosing automatically")
        c.set_sample_profile_automatically(sample, pick=pick)
        return

    c.set_sample_profile(sample, profile_selections)

@cli.command("submit")
@click.argument("target")
@click.option("-i", "--interactive", is_flag=True, help="Perform interactive"
" submission where you can manually select the profile and files")
@click.option("-p", "--profile", multiple=True, help="The profile names or IDs"
" to use")
def submit(target, interactive, profile):
    f, url = None, None
    if os.path.exists(target):
        f = target
    else:
        url = target

    if interactive and profile:
        print("--interactive and --profile are mutually exclusive")
        return

    c = client_from_env()
    if f:
        name = os.path.basename(f)
        r = c.submit_sample_file(
            name, open(f, "rb"),
            interactive=interactive,
            profiles=[{
                "profile": x
            } for x in profile]
        )
    elif url:
        r = c.submit_sample_url(
            url, interactive=interactive,
            profiles=[{
                "profile": x
            } for x in profile]
        )
    else:
        print("Please specify -f file or -u url")
        return

    print("Sample submitted")
    print("  ID:       %s" % r["id"])
    print("  Status:   %s" % r["status"])
    if f:
        print("  Filename: %s" % r["filename"])
    else:
        print("  URL:      %s" % r["url"])

    if interactive:
        time.sleep(2)
        prompt_select_profile(c, r["id"])

@cli.command("select-profile")
@click.argument("sample")
def select_profile(sample):
    c = client_from_env()
    prompt_select_profile(c, sample)

@cli.command("list")
@click.option("-n", default=20, help="The maximum number of samples to return")
@click.option("-p", "--public", is_flag=True, help="List public samples")
def list_samples(public, n):
    c = client_from_env()
    for i in c.public_samples(max=n) if public else c.owned_samples(max=n):
        print("%s, %s, %s: %s" % (
            i["id"],
            [x["id"] for x in i.get("tasks", [])],
            i["status"],
            i["url"] if i.get("url") else i.get("filename", "-")
        ))

@cli.command("file")
@click.argument("sample")
@click.argument("task")
@click.argument("file")
@click.option("-o", "--output", help= "The path to where the "
    "downloaded file should be saved. If `-`, the file is copied to stdout")
def get_file(sample, task, file, output):
    c = client_from_env()
    f = c.sample_task_file(sample, task, file)
    if output == "-":
        print(f)
    if not output:
        output = "".join(x for x in file if x not in "\/:*?<>|")
    with open(output, "wb") as wf:
        wf.write(f)

@cli.command("archive")
@click.argument("sample")
@click.option("-f", "--format", default="tar",
    help="The archive format. Either \"tar\" or \"zip\"")
@click.option("-o", "--output", help="The target file name. If `-`, the file "
"is copied to stdout. Defaults to the sample ID with appropriate extension")
def archive(sample, format, output):
    c = client_from_env()
    if format == "tar":
        r = c.sample_archive_tar(sample)
    elif format == "zip":
        r = c.sample_archive_zip(sample)
    else:
        print("Use --format zip or tar")
        return

    if output == "-":
        print(r)
    elif output:
        with open(output, "wb") as wf:
            wf.write(r)
    else:
        with open("%s.%s" % (sample, format), "wb") as wf:
            wf.write(r)


@cli.command("delete")
@click.argument("sample")
def delete(sample):
    c = client_from_env()
    c.delete_sample(sample)

@cli.command("report")
@click.argument("sample")
@click.option("--static", is_flag=True, help="Query the static report")
@click.option("-t", "--task", help= "The ID of the report")
def report(sample, static, task):
    c = client_from_env()
    if static:
        print("~Static Report~")
        r = c.static_report(sample)
        for f in r["files"]:
            print("%s %s" % (
                f["filename"],
                "(selected)" if f["selected"] else "")
            )
            print("  md5:", f["md5"])
            print("  tags:", f["tags"])
            print("  kind:", f["kind"])
    elif task:
        print("~%s Report~" % task)
        r = c.task_report(sample, task)
        err = r.get("errors")
        if err:
            print(err)
            return
        print(r["task"]["target"])
        print("  md5:", r["task"]["md5"])
        print("  score:", r["analysis"]["score"])
        print("  tags:", r["analysis"]["tags"])
    else:
        print("~Overview~")
        r = c.overview_report(sample)
        if r.get("errors"):
            print("Triage produced the following errors", r["errors"])
        print(r["sample"]["target"])
        print("  md5:", r["sample"]["md5"])
        print("  score:", r["analysis"]["score"])
        print("  family:", r["analysis"].get("family"))
        print("  tags:", r["analysis"]["tags"])
        print()
        for k, task in r.get("tasks", {}).items():
            print(" ", task["name"])
            print("    score:", task["score"])
            if task["kind"] != "static":
                print("    platform:", task["platform"])
            print("    tags:", task["tags"])

@cli.command("create-profile")
@click.option("--name", required=True, help="The name of the new profile")
@click.option("--tags", required=True, help="A comma separated set of tags")
@click.option("--network", help="The network type to use. Either \"internet\","
    " \"drop\" or unset")
@click.option("--timeout", required=True, type=int,
    help="The timeout of the profile")
def create_profile(name, tags, network, timeout):
    c = client_from_env()
    r = c.create_profile(name, tags.split(","), network, timeout)
    print(r)

@cli.command("delete-profile")
@click.option("-p", "--profile", required=True,
    help="The name or ID of the profile")
def delete_profile(profile):
    c = client_from_env()
    r = c.delete_profile(profile)
    print(r)

@cli.command("list-profiles")
def list_profiles():
    c = client_from_env()
    for i in c.profiles():
        print(i["name"])
        print("  timeout:", i["timeout"])
        print("  network:", i["network"])
        print("  tags:", i["tags"])
        print("  id:", i["id"])

if __name__ == "__main__":
    cli()