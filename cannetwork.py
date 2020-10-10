# Giulio Ganzerli 08/10/2020
# Class to manage the CanOPEN connection to the nodes.
import time

import canopen
from canopen.profiles.p402 import BaseNode402
from sys import platform
import logging
import os
import subprocess
import can


class CanNetwork:
    """
    WARNING: YOU SHOULD HAVE ONLY A CanNetwork OBJECT AT ANY GIVEN
             TIME IN YOUR SOFTWARE.


    """

    def __init__(self, interface_name="can0", bitrate=500000, bustype='socketcan', autoconnect=False):
        self.logger = logging.getLogger(__name__)
        self.interface_name = interface_name
        self.bitrate = bitrate
        self.bustype = bustype
        self.setup = False
        self.enabled = False
        self.connected = False
        self.network = canopen.Network()
        self.speed = 0
        self.state = "UNDEFINED"
        self.nodes_list = []
        # Check dependencies
        # Check if can interface is up and running (or turn it on forcibly)
        # Scan network
        # Identify master node.
        if platform != "linux":
            self.logger.error("This software is designed to run on a Raspberry Pi or a linux system."
                              " Windows is not supported.")
            raise OSError("This software is designed to run on a Raspberry Pi or a linux system."
                          " Windows is not supported.")
        elif os.geteuid() != 0:
            self.logger.error("This software is designed to run as root in order to make use of the CANbus.")
            raise OSError("This software is designed to run as root in order to make use of the CANbus.")
        elif not self.has_can_interface():
            self.logger.error("No CANbus interface found. Please connect a CANbus interface and restart the software.")
            raise IOError("No CANbus interface found. Please connect a CANbus interface and restart the software.")
        else:
            self.disable_can_interface()
            self.setup_can_interface()
            if self.setup:
                self.logger.info("CANbus interface setup.")
            self.enable_can_interface()
            if self.enabled:
                self.logger.info("CANbus interface enabled.")
            if autoconnect:
                self.connect()

    def has_can_interface(self):
        completed_process = subprocess.run(["ifconfig", "-a"], encoding="utf-8", capture_output=True)
        output = completed_process.stdout
        if self.interface_name in output:
            return True
        else:
            return False

    def setup_can_interface(self):
        if self.setup:
            return True
        completed_process = subprocess.run(["sudo", "ip", "link", "set", f"{self.interface_name}",
                                            "type", "can", "bitrate", f"{self.bitrate}"],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.setup = True
            return True
        else:
            self.setup = False
            self.logger.error(f"Could not setup the {self.interface_name} interface.")
            raise IOError(f"Could not setup the {self.interface_name} interface.")

    def enable_can_interface(self):
        if self.enabled:
            return True
        completed_process = subprocess.run(['sudo', 'ifconfig', f"{self.interface_name}", "up"],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.enabled = True
            return True
        else:
            self.logger.error(f"Could not enable the {self.interface_name} interface.")
            raise IOError(f"Could not enable the {self.interface_name} interface.")

    def disable_can_interface(self):
        if not self.enabled:
            return True
        completed_process = subprocess.run(['sudo', 'ifconfig', f"{self.interface_name}", "down"],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.enabled = False
            return True
        else:
            self.logger.error(f"Could not disable the {self.interface_name} interface.")
            raise IOError(f"Could not disable the {self.interface_name} interface.")

    def connect(self):
        try:
            self.network.connect(bitrate=self.bitrate, channel=self.interface_name, bustype=self.bustype)
            self.connected = True
        except OSError:
            self.connected = False
            self.logger.error(f"Could not connect on  the {self.interface_name} interface."
                              " A reboot will probably solve the problem")
            raise can.CanError(f"Could not connect on  the {self.interface_name} interface."
                               " A reboot will probably solve the problem")

    def initialize_nodes(self):
        try:
            self.network.scanner.search()
            # Give time to complete the search process
            time.sleep(0.3)
            for node_id in self.network.scanner.nodes:
                self.logger.info(f"Node number {node_id} identified")
                new_node = BaseNode402(node_id, 'TEATV31_01307E.eds')
                self.network.add_node(new_node)
                new_node.setup_402_state_machine()
                self.nodes_list.append(new_node)
            if len(self.nodes_list) > 0:
                self.logger.info(f"Node number {self.nodes_list[0].id} identified")
            else:
                self.logger.warning("No nodes found...")
        except can.CanError:
            self.connected = False
            self.logger.error("Connection was successful but no active node is completing the bus,"
                              " meaning that communication is impossible. Please setup a node before"
                              " trying to connect again")
            raise can.CanError("Connection was successful but no active node is completing the bus,"
                               " meaning that communication is impossible. Please setup a node before"
                               " trying to connect again")
        self.set_network_state("READY TO SWITCH ON")

    def set_network_state(self, state):
        if self.state != state:
            for node in self.nodes_list:
                node.state = state
            self.state = state

    def run_all_nodes(self):
        self.set_network_state("OPERATION ENABLED")

    def stop_all_nodes(self):
        self.set_network_state("SWITCHED ON")

    def set_speed_all_nodes(self, rpm):
        for node in self.nodes_list:
            node.sdo[0x6046][1].phys = rpm
        self.speed = rpm

    def read_inlet_pressure(self):
        # TODO to be implemented once we get to test a pressure sensor
        # Return a temporary value
        return 5

    def read_outlet_pressure(self):
        # TODO to be implemented once we get to test a pressure sensor
        # Return a temporary value
        return 10



