# Giulio Ganzerli 28/07/2020
# Class to manage the GSM Modem connection
import time
from sys import platform
from threading import Thread
from threading import Event
import os
import serial
import logging
import subprocess


class Sim:
    """
    Establish, monitor and use a 2G/3G modem with little to no hassle.

    This class is not portable and requires many additional libraries
    and software that may not be available on every platform. The
    constructor verifies that every requirement is met in order for
    this class to work as expected. If an issue is found, a relevant
    exception is raised. The class provides a simple interface to
     - Verify the modem state (detected, working, ...)
     - Verify the connection state (registered, connected...)
     - Change the connection state (connecting, disconnecting)
     - Get the Modem IMEI number
    Class variables are:
     - self.wants_connection: event that is fired when the user calls
        connect and cleared when the user calls disconnect
     - self.connected: event that is fired when the modem is connected
        and cleared when it disconnects
     - self.connection_t: the thread that takes care of all the
        asynchronous interactions with the modem
     - self.imei: the imei of the modem


     Further functionalities might be added in the future as needed.
    """

    def __init__(self, autoconnect=False, apn='ibox.tim.it', max_retries=5):
        """
        The constructor checks that all the requirements are met
        and initializes class variables.

        - The system must be running a Linux operating system
        - The script must be running as root (needed for sakis3g)
        - ppp must be installed
        - wvdial must be installed
        - screen must be installed
        - sakis3g must be installed (whom files are shipped with this software)

        It also tests if the modem was already connected at the time
        of execution, and if it was, then adjusts the variables.
        :param autoconnect: If True the constructor will call the
                connect method in a non-blocking fashion.
        """

        self.logger = logging.getLogger(__name__)
        self.imei = None
        self.apn = apn
        self.max_retries = max_retries
        self.wants_connection = Event()
        self.connected = Event()
        self.connection_t = Thread(target=self.connection_thread)
        self.connection_t.daemon = True

        if platform != "linux":
            self.logger.error("This software is designed to run on a Raspberry Pi or a linux system with a 3G modem"
                              " connected. Windows is not supported.")
            raise OSError("This software is designed to run on a Raspberry Pi or a linux system with a 3G modem "
                          " connected. Windows is not supported.")
        elif os.geteuid() != 0:
            self.logger.error("This software is designed to run as root in order to make use of the modem.")
            raise OSError("This software is designed to run as root in order to make use of the modem")
        else:
            packages = ["ppp", "wvdial", "screen", "sakis3g"]
            for package in packages:
                data = subprocess.Popen("whereis {}".format(package), shell=True,
                                        encoding="utf-8", stdout=subprocess.PIPE)
                output = data.communicate()
                # Output is in form "package: path/package \n" or
                # "package: \n" if not found.
                output = output[0].split('\n')
                # now output is ("package: path/package", "")
                output = output[0].split(':')
                # now output is ("package", "path/package") or ("package", "")
                output = output[1]
                if len(output) > 0:
                    self.logger.info("{} is installed and working.".format(package))
                else:
                    # TODO auto install sakis3g or display instructions
                    self.logger.error("Could not find package {0} in the system path. Please install {0} before"
                                      "running this software.".format(package))
                    raise FileNotFoundError("Could not find package {0} in the system path. Please install {0} before"
                                            "running this software.".format(package))

        # Start the thread only if all requirements are met
        self.connection_t.start()

        if self.__is_connected():
            self.wants_connection.set()
            self.logger.warning("The modem is already connected")
        if autoconnect:
            self.connect(blocking=False)

    def connect(self, blocking=True):
        """
        Connect to the Internet using the 2G/3G modem.

        :param blocking: if True, the functions returns only when the
                         modem is actually connected. If false, the
                         connection process will start but the
                         function will return immediately.
        :return:
        """
        self.wants_connection.set()
        if blocking:
            self.connected.wait()

    def disconnect(self, blocking=True):
        """
        Disconnects the 2G/3G modem from the Internet.

        :param blocking: if True, the functions returns only when the
                         modem is actually disconnected. If false, the
                         disconnection process will start but the
                         function will return immediately.
        :return:
        """
        self.wants_connection.clear()
        if blocking:
            while self.connected.is_set():
                time.sleep(0.1)

    def get_imei(self, reboot_on_fail=False) -> str:
        """
        Returns the imei of the 2G/3G modem connected on the interface
        /dev/ttyUSB0

        The function opens a serial communication, then sends the
        AT+GSN command to the modem. After a brief time.sleep() to let
        the device reply, two lines are read. The first one will be
        the command just sent while the other one will be the actual
        imei. A timeout of one second is set to assure that the
        software won't get stuck while trying to communicate via the
        serial interface.

        After the imei is found, it is saved as a class variable to
        speed up the process of obtaining it in the future.
        :param: reboot_on_fail: If True the system will reboot if
                                the modem replies with an empty
                                IMEI. (solution is to unplug and
                                plug in again the modem)
        :return: the Imei of the device
        """
        if self.imei is not None:
            return self.imei
        elif self.wants_connection.is_set():
            # Cannot provide an Imei if the modem is connected and no
            # imei was previously found
            self.logger.error("Cannot get the modem's IMEI while the user"
                              " wants the modem connected unless previously found")
            raise BlockingIOError("Cannot get the modem's IMEI while the user"
                                  " wants the modem connected unless previously found")
        elif self.connected.is_set():
            self.disconnect()

        with serial.Serial('/dev/ttyUSB0', 115200, timeout=1) as modem:
            # Send
            modem.write("AT+GSN\r".encode())
            time.sleep(0.005)
            modem.readline().decode()
            self.imei = modem.readline().decode()
            self.imei = self.imei.split('\n')[0]
            self.imei = self.imei.split('\r')[0]
            if len(self.imei) < 10:
                # TODO implement autoreboot
                self.logger.error("Could not get the IMEI.")
                raise IOError("Could not get the IMEI.")
            return self.imei

    def __disconnect_command(self):
        """
        Disconnects the 2G/3G modem using the sakis3g script
        WARNING: This is blocking and may take several seconds.

        This method is intended to be used in the connection_thread as
        it may block the execution for a long time.

        :return: True if disconnected successfully, False otherwise
        """
        completed_process = subprocess.run(['sudo', 'sakis3g', 'disconnect'],
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.connected.clear()
            return True
        else:
            self.connected.set()
            return False

    def __connect_command(self):
        """
        Connects with the 2G/3G modem using the sakis 3g script.
        WARNING: This is blocking and may take several seconds.

        This method is intended to be used in the connection_thread as
        it may block the execution for a long time.

        :return: True if connected successfully, False otherwise
        """
        completed_process = subprocess.run(['sudo', 'sakis3g', 'connect', 'USBINTERFACE="0"',
                                            'APN="{}"'.format(self.apn)], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.connected.set()
            return True
        else:
            self.connected.clear()
            return False

    def __is_connected(self):
        """
        Gets the connection state using the sakis3g script.
        WARNING: This is blocking and may take several seconds.

        This method is intended to be used solely in the
        connection_thread as it may block the execution for a long
        time. It determines the state of the connection by reading
        the exit value of the "sakis3g connected" command.

        :return: True if connected, False otherwise
        """
        completed_process = subprocess.run(["sakis3g", "connected"], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        return_value = completed_process.returncode
        if return_value == 0:
            self.connected.set()
            return True
        else:
            self.connected.clear()
            return False

    def connection_thread(self):
        # while user wants connection, assures that everything works
        # can be stopped via wants_connection
        print("Thread started")
        self.logger.info("Modem connection thread started")
        while True:
            self.wants_connection.wait()
            print("Connection request received")
            self.logger.info("Connection request received")
            while self.wants_connection.is_set():
                if not self.__is_connected():
                    # Note that __is_connected already updates the connected Event
                    # Try to connect MAX_RETRIES times
                    for i in range(1, self.max_retries):
                        if self.__connect_command():
                            print("Connected successfully")
                            self.logger.info("Connected successfully")
                            break
                        elif i == self.max_retries:
                            # TODO implement autoreboot
                            self.logger.error("Connection failed for an unknown reason.")
                            raise ConnectionError("Connection failed for an unknown reason.")
                time.sleep(1)
                # Monitor connection once every second

            # If the excecution reached this point, it means that
            # self.wants_connection has been cleared
            # Try to disconnect MAX_RETRIES times
            print("Thread disconnecting")
            for i in range(1, self.max_retries):
                if self.__disconnect_command():
                    print("Disconnected successfully")
                    self.logger.info("Disconnected successfully")
                    break
                elif i == self.max_retries:
                    # TODO implement autoreboot
                    self.logger.error("Disconnection failed for an unknown reason.")
                    raise ConnectionError("Disconnection failed for an unknown reason.")
