import logging
from datetime import datetime
from queue import Empty
from multiprocessing import Process
from interfaces.cannetwork import CanNetwork
from picandb.settingsmanager import SettingsManager


# TODO proper class conversion

class CanProcess(Process):

    def __init__(self, read_queue, write_queue, interface_name="can0", bitrate=500000, bustype='socketcan'):
        super(CanProcess, self).__init__()
        self.read_queue = read_queue
        self.write_queue = write_queue
        self.interface_name = interface_name
        self.bitrate = bitrate
        self.bustype = bustype
        self.logger = logging.getLogger(__name__ + '.can_process')
        self.settings = SettingsManager("piCANclient.db")
        self.can_network = None

        # Variables declaration
        self.anti_drip_min_period = None
        self.target_pressure = None
        self.anti_drip_start_count_limit = None
        self.min_inlet_pressure = None
        self.max_inlet_pressure = None
        self.anti_drip_time_limit = None
        self.anti_drip = self.load_boolean("Antisgocc_OK")
        self.operator_pump_start = self.load_boolean("Operator_Pump_start")
        self.running = False

    def load_boolean(self, field_name: str, invert=False):
        setting_string = self.settings.get_setting("Antisgocc_OK")
        if (setting_string == "1" and not invert) or (setting_string == "0" and invert):
            return True
        else:
            return False

    def __build_data__(self):
        d = {"inlet_pressure": self.can_network.read_inlet_pressure(),
             "inlet_temperature": self.can_network.read_inlet_temperature(),
             "outlet_pressure": self.can_network.read_outlet_pressure(),
             "outlet_pressure_target": self.settings.get_setting("Pressione_Uscita_Target"),
             "working_hours_counter": self.settings.get_setting("impianto_BK_Counter_hour"),
             "working_minutes_counter": self.settings.get_setting("impianto_BK_Counter_min"),
             "anti_drip": self.anti_drip,
             "alarms": str(self.can_network.get_faulty_nodes()),
             "tl_service": self.settings.get_setting("impianto_TL_SERVICE"),
             "bk_service": self.settings.get_setting("impianto_BK_SERVICE"),
             "rb_service": self.settings.get_setting("impianto_RB_SERVICE"),
             "run": self.operator_pump_start,
             "running": self.running}
        return d

    def initialize_settings(self):
        self.anti_drip_min_period = int(self.settings.get_setting("AntisgoccDurataPartenze"))
        self.target_pressure = int(self.settings.get_setting("Pressione_Uscita_Target"))
        self.anti_drip_start_count_limit = int(self.settings.get_setting("AntisgoccNpartenze"))
        self.min_inlet_pressure = int(self.settings.get_setting("Pressione_Ingresso_Min"))
        self.max_inlet_pressure = int(self.settings.get_setting("Pressione_Ingresso_Max"))
        self.anti_drip_time_limit = int(self.settings.get_setting("AntisgoccPeriodoControllo"))
        self.anti_drip = self.load_boolean("Antisgocc_OK")
        self.operator_pump_start = self.load_boolean("Operator_Pump_start")

    def run(self):
        self.logger.info("CANBus Interface Process started")
        # TODO at process start all settings should be loaded and
        # TODO communicated via CAN Bus
        last_started = None
        anti_drip_start_count = 0
        anti_drip_current_time_frame = datetime.now()
        self.initialize_settings()
        self.can_network = CanNetwork(bitrate=self.bitrate, bustype=self.bustype,
                                      interface_name=self.interface_name, autoconnect=True)
        self.can_network.connect()
        self.can_network.initialize_nodes()
        while True:
            try:
                command = self.read_queue.get(timeout=1)
                result = "INVALID"
                logging.info("Executing {}".format(command))
                if command == "RUN":
                    self.operator_pump_start = True
                    self.can_network.reset_faulty_nodes()
                    self.settings.update_setting("Operator_Pump_start", 1)
                    result = "OK"
                elif command == "STOP":
                    self.operator_pump_start = False
                    self.settings.update_setting("Operator_Pump_start", 0)
                    # A stop may be very important, so it's sent immediately.
                    self.can_network.stop_all_nodes()
                    self.running = False
                    result = "OK"
                elif command == "GET_INFO":
                    result = self.__build_data__()
                elif command == "RESET_PRESSURE_TARGET":
                    self.target_pressure = int(self.settings.get_setting("Pressione_Uscita_Target"))
                    result = "OK"
                self.write_queue.put(result)
            except Empty:
                # Phase b). No commands were found. Then read data from
                # pressure sensors, read settings from the database and
                # execute

                # 1. If pumps have been running for more than anti_drip_time_limit
                #    then increase the anti_drip_start_count. If last started is None
                #    then it means that everything has already been calculated (or
                #    it has yet to start)
                if last_started is not None:
                    print(f"seconds {(datetime.now() - last_started).total_seconds()}")
                    print(f"min per {self.anti_drip_min_period}")
                    print(f"count {anti_drip_start_count}")
                if (last_started is not None and
                   (datetime.now() - last_started).total_seconds() >= self.anti_drip_min_period):
                    anti_drip_start_count += 1
                    last_started = None

                # 2. If the time window has expired, reset it. Otherwise, check the counter.
                #    If necessary, stop everything and set the anti_drip.
                if (datetime.now() - anti_drip_current_time_frame).total_seconds() > self.anti_drip_time_limit:
                    anti_drip_current_time_frame = datetime.now()
                    anti_drip_start_count = 0
                elif anti_drip_start_count == self.anti_drip_start_count_limit:
                    self.settings.update_setting("Antisgocc_OK", 0)
                    self.anti_drip = True

                # 3. Update all relevant variables
                tl_service = int(self.settings.get_setting("impianto_TL_SERVICE"))
                bk_service = int(self.settings.get_setting("impianto_BK_SERVICE"))
                rb_service = int(self.settings.get_setting("impianto_RB_SERVICE"))

                # 4. Read pressure values and start or stop the pumps as necessary
                outlet_pressure = self.can_network.read_outlet_pressure()/10
                inlet_pressure = self.can_network.read_inlet_pressure()

                if inlet_pressure == 1:
                    self.settings.update_setting("Pressione_Ingresso_OK", 1)
                    if tl_service == 0 and bk_service == 0 and rb_service == 0:
                        if (outlet_pressure < self.target_pressure and
                           not self.anti_drip and self.operator_pump_start == 1):
                            # TODO Use inverter's PID
                            difference = self.target_pressure - outlet_pressure
                            if not self.running:
                                self.can_network.run_all_nodes()
                                self.running = True
                                if last_started is None:
                                    last_started = datetime.now()
                            if difference > 0:
                                # *30 to convert rpm in hertz. 1500 is max rpm
                                self.can_network.set_speed_all_nodes(min(difference * 30, 3000))
                            else:
                                # Target pressure reached
                                self.can_network.set_speed_all_nodes(0)
                                self.can_network.stop_all_nodes()
                                self.running = False
                        else:
                            self.can_network.stop_all_nodes()
                            self.running = False
                    else:
                        self.can_network.stop_all_nodes()
                        self.running = False
                        self.logger.warning(f"System stopped for a time limit:"
                                            f" TL:{tl_service}, BK:{bk_service}, RB:{rb_service}")
                else:
                    self.can_network.stop_all_nodes()
                    self.running = False
                    self.settings.update_setting("Pressione_Ingresso_OK", 0)
                    self.logger.warning(f"Inlet pressure of {inlet_pressure}bar, is outside limits. Pumps not started.")

                self.settings.update_setting("Pressione_Uscita", outlet_pressure)
                self.settings.update_setting("Pressione_Ingresso", inlet_pressure)

