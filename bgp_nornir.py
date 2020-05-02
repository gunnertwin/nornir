'''
This module is a BGP program that allows you to add or remove BGP neighbours
'''

import re
from pathlib import Path
from nornir import InitNornir
from nornir.plugins.functions.text import print_result
from nornir.plugins.tasks.networking import netmiko_send_command, napalm_get
from nornir.plugins.tasks import networking, data, text, files


def get_config(task):

    '''
    This function obtains the current running config of your running hosts
    '''

    loopback_exists = task.run(task=netmiko_send_command,
                               command_string="show ip int br | i Loopback")
    interface_exists = task.run(task=netmiko_send_command,
                                command_string="sh run | i GigabitEthernet2.")
    pl_exists = task.run(task=netmiko_send_command,
                         command_string="show run | i ^ip prefix-list")
    rm_exists = task.run(task=netmiko_send_command,
                         command_string="show route-map")
    bgp_exists = task.run(task=netmiko_send_command,
                          command_string="show bgp")

    if "Loopback" not in loopback_exists[0].result:
        task.run(task=networking.napalm_configure,
                 configuration="""
        int Loopback1
        Description Configured by Nornir""")

    if "GigabitEthernet2." not in interface_exists[0].result:
        task.run(task=networking.napalm_configure,
                 configuration="""
        int GigabitEthernet2.1
        Description Configured by Nornir""")

    if "prefix-list PL_BGP_" not in pl_exists[0].result:
        task.run(task=networking.napalm_configure,
                 configuration="ip prefix-list PL_BGP_Temp seq 5 permit 1.1.1.1/32")

    if "route-map RM_BGP_" not in rm_exists[0].result:
        task.run(task=networking.napalm_configure,
                 configuration="route-map RM_BGP_Temp")

    if "BGP not active" in bgp_exists[0].result:
        task.run(task=networking.napalm_configure,
                 configuration="router bgp 1000")

    print(f"{task.host.name}: Obtaining running configuration")

    result = task.run(
        task=napalm_get,
        getters=["config"], getters_options={
            "config":{"retrieve":"running"}})

    config_running = result[0].result["config"]["running"].split("\n")[6:]

    Path("running_configs").mkdir(exist_ok=True)
    with open(f"running_configs/{task.host.name}_config", "w") as file:
        for element in config_running:
            file.write(element+'\n')

    with open(f"running_configs/{task.host.name}_config", "r") as file:
        task.host["config_running"] = file.read()


def initialization(task):

    '''
    This function prepares the configuration of your running hosts and renders
    the Jinja2 templates so that confid can be merged by Napalm
    '''

    host = task.host.name

    loopbacks_conf_file = task.run(task=data.load_yaml,
                                   file=f"deploy_files/{host}/loopbacks_conf.yaml")
    pl_rm_conf_file = task.run(task=data.load_yaml,
                               file=f"deploy_files/{host}/pl_rm.yaml")
    bgp_conf_file = task.run(task=data.load_yaml,
                             file=f"deploy_files/{host}/bgp_conf.yaml")

    interfaces_yaml = loopbacks_conf_file[0].result
    pl_rm_yaml = pl_rm_conf_file[0].result
    bgp_yaml = bgp_conf_file[0].result

    loopbacks_rendered_config = task.run(task=text.template_file,
                                         template="loopbacks.j2",
                                         path="./templates",
                                         rules=interfaces_yaml)
    interfaces_rendered_config = task.run(task=text.template_file,
                                          template="interfaces.j2",
                                          path="./templates",
                                          rules=interfaces_yaml)
    pl_rendered_config = task.run(task=text.template_file,
                                  template="prefix_list.j2",
                                  path="./templates",
                                  rules=pl_rm_yaml)
    rm_rendered_config = task.run(task=text.template_file,
                                  template="route_map.j2",
                                  path="./templates",
                                  rules=pl_rm_yaml)
    bgp_rendered_config = task.run(task=text.template_file,
                                   template="bgp.j2",
                                   path="./templates",
                                   rules=bgp_yaml)

    loopbacks_rendered_config = loopbacks_rendered_config[0].result
    interfaces_rendered_config = interfaces_rendered_config[0].result
    pl_rendered_config = pl_rendered_config[0].result
    rm_rendered_config = rm_rendered_config[0].result
    bgp_rendered_config = bgp_rendered_config[0].result

    task.run(task=files.write_file,
             filename=f"rendered_configs/{host}/loopbacks_final",
             content=loopbacks_rendered_config)
    task.run(task=files.write_file,
             filename=f"rendered_configs/{host}/interfaces_final",
             content=interfaces_rendered_config)
    task.run(task=files.write_file,
             filename=f"rendered_configs/{host}/pl_final",
             content=pl_rendered_config)
    task.run(task=files.write_file,
             filename=f"rendered_configs/{host}/rm_final",
             content=rm_rendered_config)
    task.run(task=files.write_file,
             filename=f"rendered_configs/{host}/bgp_final",
             content=bgp_rendered_config)

    with open(f"rendered_configs/{host}/loopbacks_final", "r") as file:
        task.host["loop_config"] = file.read()

    with open(f"rendered_configs/{host}/interfaces_final", "r") as file:
        task.host["int_config"] = file.read()

    with open(f"rendered_configs/{host}/pl_final", "r") as file:
        task.host["pl_config"] = file.read()

    with open(f"rendered_configs/{host}/rm_final", "r") as file:
        task.host["rm_config"] = file.read()

    with open(f"rendered_configs/{host}/bgp_final", "r") as file:
        task.host["bgp_config"] = file.read()

def configure_loopbacks(task):

    '''
    This function add the Loopbacks configuration to the configuration file
    '''

    first_pattern = re.compile(r"^\w+\s\w+", flags=re.M | re.I)
    entries = first_pattern.findall(task.host["loop_config"])

    #Strip away the "interface Loopback" field away from the match
    loopback_list = []
    for entry in entries:
        entry = entry.replace("interface Loopback", "")
        loopback_list.append(entry)

    #Grab all interface IDs and seperate it with a pipe to use in the next regex script
    loopbacks = "|"
    loopbacks = loopbacks.join(loopback_list)

    #Regex pattern matches all the interface blocks that match the interface IDs we grabbed earlier
    pattern = re.compile(f"interface Loopback(?:{loopbacks})(?:\n .+)+",
                         flags=re.M | re.I)

    #Regex pattern matches all the interface blocks that DON'T match the interface IDs we grabbed
    #earlier, that have the word "Nornir" in the description field.
    pattern2 = re.compile(f"interface Loopback(?!(?:{loopbacks})).*\n.*Nornir(?:\n .+|)+",
                          flags=re.M | re.I)

    print(f"{task.host.name}: Adding Loopbacks configuration to config file")

    #This section takes what's in the final interface config and replaces the like for like on
    #going config file.
    entries = pattern.findall(task.host["config_running"])
    if entries:
        count = len(entries)
        for entry in entries:
            if count != 1:
                task.host["config_running"] = re.sub(entry, "",
                                                     task.host["config_running"])
                count -= 1
            else:
                task.host["config_running"] = re.sub(entry, task.host["loop_config"],
                                                     task.host["config_running"])

    #If interface to merge in config doesn't exist in the config file, perform a merge operation.
    entries = pattern2.findall(task.host["config_running"])
    for entry in entries:
        task.host["config_running"] = re.sub(entry, task.host["loop_config"],
                                             task.host["config_running"])


def configure_interfaces(task):

    '''
    This function add the Interfaces configuration to the configuration file
    '''

    #Use regex to look for the interface ID, such as "2.50" from "GigabitEthernet2.50"
    first_pattern = re.compile(r"^int\w+\sGig\w+\d\.\d+$", flags=re.M | re.I)
    entries = first_pattern.findall(task.host["int_config"])

    #Strip away the "interface GigabitEthernet" field away from the match
    interface_list = []
    for entry in entries:
        entry = entry.replace("interface GigabitEthernet", "")
        interface_list.append(entry)

    #Grab all interface IDs and seperate it with a pipe to use in the next regex script
    interfaces = "|"
    interfaces = interfaces.join(interface_list)

    #Regex pattern matches all the interface blocks that match the interface IDs we grabbed earlier
    pattern = re.compile(f"interface GigabitEthernet(?:{interfaces})(?:\n .+)+", flags=re.M | re.I)

    #Regex pattern matches all the interface blocks that DON'T match the interface IDs
    #we grabbed earlier, that have the word "Nornir" in the description field.
    pattern2 = re.compile(f"interface GigabitEthernet(?!(?:{interfaces})).*\n.*Nornir(?:\n .+|)+",
                          flags=re.M | re.I)

    #Try Except methods are here just in case the "new_config_file" does not exist which it won't
    #if no Loopback interfaces are in the config.
    #For each entry, delete the interface config. This is represented by replacing the regex match
    #with and empty string.

    print(f"{task.host.name}: Adding Interfaces configuration to config file")
    #This section takes what's in the final interface config and replaces the like for like on
    #going config file.
    entries = pattern.findall(task.host["config_running"])
    if entries:
        count = len(entries)
        for entry in entries:
            if count != 1:
                task.host["config_running"] = re.sub(entry, "",
                                                     task.host["config_running"])
                count -= 1
            else:
                task.host["config_running"] = re.sub(entry, task.host["int_config"],
                                                     task.host["config_running"])

    entries = pattern2.findall(task.host["config_running"])
    for entry in entries:
        task.host["config_running"] = re.sub(entry, task.host["int_config"],
                                             task.host["config_running"])


def configure_pl_rm(task):

    '''
    This function add the ip prefix list and route-maps configuration to the configuration file
    '''

    pattern = re.compile("^ip prefix-list PL_BGP_.+$", flags=re.M | re.I)
    entries = pattern.findall(task.host["config_running"])
    print(f"{task.host.name}: Adding prefix list configuration to config file")
    count = len(entries)
    if entries:
        for entry in entries:
            if count != 1:
                task.host["config_running"] = re.sub(entry, "",
                                                     task.host["config_running"])
                count -= 1
            else:
                task.host["config_running"] = re.sub(entry, task.host["pl_config"],
                                                     task.host["config_running"])

    pattern = re.compile("^route-map RM_BGP_.*(?:\n .+)*", flags=re.M | re.I)
    entries = pattern.findall(task.host["config_running"])
    print(f"{task.host.name}: Adding route map configuration to config file")
    count = len(entries)
    if entries:
        for entry in entries:
            if count != 1:
                task.host["config_running"] = re.sub(entry, "",
                                                     task.host["config_running"])
                count -= 1
            else:
                task.host["config_running"] = re.sub(entry, task.host["rm_config"],
                                                     task.host["config_running"])


def configure_bgp(task):

    '''
    This function add the BGP configuration to the configuration file
    '''

    print(f"{task.host.name}: Adding BGP configuration to config file")
    pattern = re.compile(r"^router\sbgp\s\d+(?:\n .*)*", flags=re.M | re.I)
    task.host["config_running"] = re.sub(pattern, task.host["bgp_config"],
                                         task.host["config_running"])

def replace_config(task):

    '''
    This function merges the new configuration to the hosts
    '''
    print(f"{task.host.name}: Pushing final configuration")
    task.run(task=networking.napalm_configure,
             configuration=task.host["config_running"],
             replace=True,
             dry_run=False)


def main():

    '''
    This is the main function that initiates the Nornir script
    '''

    nornir = InitNornir(config_file="config.yaml")
    nornir.run(task=get_config, num_workers=10)
    nornir.run(task=initialization, num_workers=10)
    nornir.run(task=configure_loopbacks, num_workers=10)
    nornir.run(task=configure_interfaces, num_workers=10)
    nornir.run(task=configure_pl_rm, num_workers=10)
    nornir.run(task=configure_bgp, num_workers=10)
    result = nornir.run(task=replace_config, num_workers=10)
    print_result(result)

if __name__ == "__main__":
    main()
