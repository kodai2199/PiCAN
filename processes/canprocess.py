import logging
from datetime import datetime
from queue import Empty
from multiprocessing import Process
from processes.cannetwork import CanNetwork
from picandb.settingsmanager import SettingsManager


# TODO proper class conversion

class CanProcess(Process):

    def __init__(self, read_queue, write_queue):
        super().__init__()
        self.read_queue = read_queue
        self.write_queue = write_queue

        self.logger = logging.getLogger(__name__ + '.can_process')
        self.settings = SettingsManager("piCANclient.db")
        self.can_network = None

        # Variables initialization

        self.anti_drip = self.load_anti_drip()
        self.running = False

    def load_anti_drip(self):
        anti_drip_string = self.settings.get_setting("Antisgocc_OK")
        if anti_drip_string == "0":
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
             "alarms": self.can_network.get_faulty_nodes(),
             "tl_service": self.settings.get_setting("impianto_TL_SERVICE"),
             "bk_service": self.settings.get_setting("impianto_BK_SERVICE"),
             "rb_service": self.settings.get_setting("impianto_RB_SERVICE"),
             "run": self.settings.get_setting("Operator_Pump_start"),
             "running": self.running}
        return d

    def check_inlet_pressure_requirements(self):
        pass

    def check_requirements(self):
        pass

    def run_nodes(self):
        pass

    def run(self):
        # TODO at process start all settings should be loaded and
        # TODO communicated via CAN Bus
        last_started = None
        anti_drip_start_count = 0
        anti_drip_start_count_limit = int(self.settings.get_setting("AntisgoccNpartenze"))
        anti_drip_min_period = int(self.settings.get_setting("AntisgoccDurataPartenze"))
        target_pressure = int(self.settings.get_setting("Pressione_Uscita_Target"))
        min_inlet_pressure = int(self.settings.get_setting("Pressione_Ingresso_Min"))
        max_inlet_pressure = int(self.settings.get_setting("Pressione_Ingresso_Max"))
        anti_drip_time_limit = int(self.settings.get_setting("AntisgoccPeriodoControllo"))
        if self.settings.get_setting("Antisgocc_OK") == 0:
            # If it's not ok then it's activated...
            self.anti_drip = True
        else:
            self.anti_drip = False
        operator_pump_start = self.settings.get_setting("Operator_Pump_start")
        anti_drip_current_time_frame = datetime.now()
        self.can_network = CanNetwork()
        self.can_network.connect()
        self.can_network.initialize_nodes()
        while True:
            try:
                # Check for commands. Remember the .get() is blocking so the
                # process will wait until a command needs to be executed.
                command = self.read_queue.get(timeout=0.5)
                result = "INVALID"
                logging.info("Executing {}".format(command))
                # TODO: Implement actual command sending
                if command == "RUN":
                    operator_pump_start = 1
                    self.settings.update_setting("Operator_Pump_start", 1)
                    result = "OK"
                elif command == "STOP":
                    operator_pump_start = 0
                    self.settings.update_setting("Operator_Pump_start", 0)
                    self.can_network.stop_all_nodes()
                    result = "OK"
                elif command == "GET_INFO":
                    result = self.__build_data__()
                print("EXECUTED {}".format(command))
                self.write_queue.put(result)
            except Empty:
                # Phase b). No commands were found. Then read data from
                # pressure sensors, read settings from the database and
                # execute

                # 1. If pumps have been running for more than anti_drip_time_limit
                #    then increase the anti_drip_start_count. If last started is None
                #    then it means that everything has already been calculated (or
                #    it has yet to start)
                if last_started is not None and (datetime.now() - last_started).total_seconds() >= anti_drip_min_period:
                    anti_drip_start_count += 1
                    last_started = None

                # 2. If the time window has expired, reset it. Otherwise, check the counter.
                #    If necessary, stop everything and set the anti_drip.
                if (datetime.now() - anti_drip_current_time_frame).total_seconds() > anti_drip_time_limit:
                    anti_drip_current_time_frame = datetime.now()
                    anti_drip_start_count = 0
                elif anti_drip_start_count == anti_drip_start_count_limit:
                    self.settings.update_setting("Antisgocc_OK", 0)
                    anti_drip = True

                # 3. Update all relevant variables
                tl_service = int(self.settings.get_setting("impianto_TL_SERVICE"))
                bk_service = int(self.settings.get_setting("impianto_BK_SERVICE"))
                rb_service = int(self.settings.get_setting("impianto_RB_SERVICE"))

                # 4. Read pressure values and start or stop the pumps as necessary
                outlet_pressure = self.can_network.read_outlet_pressure()
                inlet_pressure = self.can_network.read_inlet_pressure()

                if min_inlet_pressure < inlet_pressure < max_inlet_pressure:
                    self.settings.update_setting("Pressione_Ingresso_OK", 1)
                    if tl_service == 0 and bk_service == 0 and rb_service == 0:
                        if outlet_pressure < target_pressure and not anti_drip and operator_pump_start == 1:
                            # TODO Use inverter's PID
                            # could also smartly set speed...
                            self.can_network.run_all_nodes()
                            last_started = datetime.now()
                        else:
                            self.can_network.stop_all_nodes()
                    else:
                        self.can_network.stop_all_nodes()
                        self.logger.warning(f"System stopped for a time limit:"
                                       f" TL:{tl_service}, BK:{bk_service}, RB:{rb_service}")
                else:
                    self.settings.update_setting("Pressione_Ingresso_OK", 0)
                    self.logger.warning(f"Inlet pressure of {inlet_pressure}bar, is outside limits. Pumps not started.")
                # TODO check for nodes in alarm

                self.settings.update_setting("Pressione_Uscita", outlet_pressure)
                self.settings.update_setting("Pressione_Ingresso", inlet_pressure)

