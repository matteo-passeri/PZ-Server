#!/usr/bin/env python3
# Quick helper script to edit the JVM configuration file and the server ini file

import argparse
import json


def update_config_file(file_path: str, key: str, new_value: str) -> None:
    """Update a key in a configuration file, appending it when absent."""
    with open(file_path, "r") as file:
        lines = file.readlines()

    updated_lines = []
    key_found = False
    for line in lines:
        if line.startswith(f"{key}="):
            updated_lines.append(f"{key}={new_value}\n")
            key_found = True
        else:
            updated_lines.append(line)

    if not key_found:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"
        updated_lines.append(f"{key}={new_value}\n")

    with open(file_path, "w") as file:
        file.writelines(updated_lines)


def update_jvm_config(file_path: str, max_memory: str) -> None:
    """Update JVM maximum and minimum memory settings."""
    with open(file_path, "r") as config_file:
        config = json.load(config_file)

    for item in config["vmArgs"]:
        if item.startswith("-Xmx"):
            config["vmArgs"].remove(item)
        if item.startswith("-Xms"):
            config["vmArgs"].remove(item)

    config["vmArgs"].append(f"-Xmx{max_memory}")
    config["vmArgs"].append(f"-Xms{max_memory}")

    with open(file_path, "w") as config_file:
        json.dump(config, config_file, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update configuration files")
    parser.add_argument("--config", type=str, required=True, help="The path to the configuration file")
    parser.add_argument("--key", type=str, nargs="?", help="The key to update")
    parser.add_argument("--value", type=str, nargs="?", help="The new value for the key")
    parser.add_argument("--memory", type=str, nargs="?", help="The new value for the max memory setting")
    parser.add_argument("--action", type=str, choices=["update-jvm", "update-config"], default="update-config", help="The action to perform")
    args = parser.parse_args()

    if args.action == "update-config":
        update_config_file(args.config, args.key, args.value)
    elif args.action == "update-jvm":
        update_jvm_config(args.config, args.memory)
