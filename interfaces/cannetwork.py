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

    This class manages the CANbus interface, the CAN network connection,
    the initialization of the nodes and 

    """
    FAULT = 0
    SWITCH_ON_DISABLED = 0x80
    SWITCHED_ON = 0x07
    OPERATION_ENABLED = 0x0F

    def __init__(self, interface_name="can0", bitrate=500000, bustype='socketcan', autoconnect=False):
        self.logger = logging.getLogger(__name__)
        self.interface_name = interface_name
        self.bitrate = bitrate
        self.bustype = bustype
        self.setup = False
        self.enabled = False
        self.connected = False
        self.network = None
        self.speed = 0
        self.state = None
        self.nodes_list = []
        # Check dependencies
        # TODO install canopen from github pip install https://github.com/christiansandberg/canopen/archive/master.zip
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
            time.sleep(0.2)
            self.setup_can_interface()
            time.sleep(0.2)
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
        completed_process = subprocess.run(["sudo", 'ifconfig', f"{self.interface_name}", "up"],
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
            self.network = canopen.Network()
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
            # For some reason, reconnect is needed...
            self.connect()
            self.network.scanner.search()
            # Give time to complete the search process
            time.sleep(0.5)
            self.logger.info(f"CAN Network scan result: nodes number {self.network.scanner.nodes}")
            for node_id in self.network.scanner.nodes:
                new_node = BaseNode402(node_id, 'LOVATO_VLB3.eds')
                self.network.add_node(new_node)
                new_node.nmt.state = "PRE-OPERATIONAL"
                time.sleep(0.2)
                new_node.rpdo.read()
                new_node.tpdo.read()
                new_node.rpdo[1].enable = True
                new_node.rpdo[1].start(0.05)
                new_node.nmt.state = 'OPERATIONAL'
                time.sleep(0.2)
                self.reset_faulty_node(new_node)
                new_node.rpdo[1]['CiA: Controlword'].raw = self.SWITCH_ON_DISABLED
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
        # Wait before setting all to ready
        time.sleep(0.5)
        self.set_network_state(self.SWITCHED_ON)

    def set_network_state(self, state):
        # Ignored fault
        if self.state != state:
            for node in self.nodes_list:
                if not self.is_faulty(node):
                    node.rpdo[1]['CiA: Controlword'].raw = state
            self.state = state

    def get_faulty_nodes(self):
        faulty = []
        for node in self.nodes_list:
            if self.is_faulty(node):
                faulty.append(node.id)
        return faulty

    def is_faulty(self, node: BaseNode402) -> bool:
        if node.tpdo[1]['CiA: Statusword'].bits[3]:
            return True
        else:
            return False

    def reset_faulty_node(self, node: BaseNode402) -> None:
        if self.is_faulty(node):
            node.rpdo[1]['CiA: Controlword'].bits[7] = 1
            time.sleep(0.1)
            node.rpdo[1]['CiA: Controlword'].bits[7] = 0
            time.sleep(0.1)

    def reset_faulty_nodes(self):
        for node in self.nodes_list:
            self.reset_faulty_node(node)

    def get_state(self, node: BaseNode402) -> int:
        if self.is_faulty(node):
            return self.FAULT
        elif node.tpdo[1]['CiA: Statusword'].bits[2]:
            return self.OPERATION_ENABLED
        elif node.tpdo[1]['CiA: Statusword'].bits[1]:
            return self.SWITCHED_ON
        else:
            return self.SWITCH_ON_DISABLED

    def run_all_nodes(self):
        self.set_network_state(self.SWITCHED_ON)
        self.set_network_state(self.OPERATION_ENABLED)

    def stop_all_nodes(self):
        self.set_network_state(self.SWITCHED_ON)

    def set_speed_all_nodes(self, rpm):
        for node in self.nodes_list:
            node.sdo[0x6042].phys = rpm
        self.speed = rpm

    def read_outlet_pressure(self):
        return self.nodes_list[0].sdo[0x2DA4][1].raw

    def read_inlet_temperature(self):
        return self.nodes_list[0].sdo[0x60FD].bits[16]

    def read_inlet_pressure(self):
        return self.nodes_list[0].sdo[0x60FD].bits[17]

    # def read_inlet_pressure(self):
    # to be implemented if we get to test a pressure sensor
    # Return a temporary value
    #   return 5
