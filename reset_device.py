from nornir import InitNornir
from nornir.plugins.tasks import networking
from nornir.plugins.functions.text import print_result
from nornir.plugins.tasks.networking import netmiko_send_command

def replace_config(task):

    command = "no router bgp 1000"

    task.run(task=networking.napalm_configure, configuration=command)
    
    with open(f"startup_configs/{task.host.name}_config", "r") as f:
        task.host["config_startup"] = f.read()

    #import ipdb; ipdb.set_trace()
    print(f"{task.host.name}: Pushing startup configuration")
    #task.run(task=networking.napalm_configure, configuration=task.host["config_startup"], replace=True, dry_run=False)
    result = task.run(task=networking.napalm_configure, filename=f"startup_configs/{task.host.name}_config", replace=True, dry_run=False)
    print_result(result)
    
def main():
    nr = InitNornir(config_file="config.yaml")
    nr.run(task=replace_config, num_workers=10)
    
    
if __name__ == "__main__":
    main()