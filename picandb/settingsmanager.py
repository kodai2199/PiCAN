from picandb.dblink import DBLink
import logging


class SettingsManager(DBLink):

    def initialize(self):
        # A long function that initializes the database and every setting requested
        self.connect()
        self.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='settings'")
        result = self.cursor.fetchone()[0]
        if result == 1:
            # If the table exists the program will assume it was already
            # initialized
            logging.info("Database already initialized.")
        else:
            # If they do not exist already, create the data and
            # settings table. The settings table will have records
            # in a key:value pair
            # record, containing the last used settings.
            # The data table will have a record for every time the
            # can_interface_process fetches data from the CANbus.
            # Only data that has to be sent via web will be recorded this way
            logging.info("Database not initialized. Creating data and settings table")
            self.execute("CREATE TABLE IF NOT EXISTS data("
                         "id integer primary key autoincrement,"
                         "CPx varchar(255) not null default 0,"
                         "inlet_pressure integer not null default 0,"
                         "inlet_temperature integer not null default 0,"
                         "outlet_pressure integer not null default 0,"
                         "working_hours_counter integer not null default 0,"
                         "working_minutes_counter integer not null default 0,"
                         "anti_drip integer not null default 0,"
                         "time_limit integer not null default 0,"
                         "start_code varchar(255) not null default '0',"
                         "alarm integer not null default 0,"
                         "bk_service integer not null default 0,"
                         "tl_service integer not null default 0,"
                         "rb_service integer not null default 0,"
                         "run integer not null default 0,"
                         "timestamp text not null default '')")
            self.execute("CREATE TABLE IF NOT EXISTS settings("
                         "key varchar(255) primary key,"
                         "value varchar(255) default null)")
            logging.info("Tables created, inserting default settings records...")
            insert_query = ("INSERT INTO settings(key, value) VALUES ("
                            "?, ?)")
            records = [("IMEI_impianto", "AAAAA BBBBB CCCCC DDDDD")]
            settings_list = ["CPx",
                             "Operator_Pump_start",
                             "impianto_RB_SERVICE",
                             "impianto_RB_Counter_sec",
                             "impianto_RB_Counter_min",
                             "impianto_RB_Counter_hour",
                             "impianto_RB_Counter_Reset",
                             "impianto_RB_Counter_SetCounter",
                             "impianto_RB_Counter_minuti",
                             "impianto_RB_Counter_secondi",
                             "impianto_RB_Counter_ore",
                             "impianto_BK_SERVICE",
                             "impianto_BK_Counter_sec",
                             "impianto_BK_Counter_min",
                             "impianto_BK_Counter_hour",
                             "impianto_BK_Counter_Reset",
                             "impianto_BK_Counter_SetCounter",
                             "impianto_BK_Counter_minuti",
                             "impianto_BK_Counter_secondi",
                             "impianto_BK_Counter_ore",
                             "impianto_TL_SERVICE",
                             "impianto_TL_Counter_sec",
                             "impianto_TL_Counter_min",
                             "impianto_TL_Counter_hour",
                             "impianto_TL_Counter_Reset",
                             "impianto_TL_Counter_SetCounter",
                             "impianto_TL_Counter_minuti",
                             "impianto_TL_Counter_secondi",
                             "impianto_TL_Counter_ore",
                             "IMEI_impianto_OK",
                             "Codice_Impianto",
                             "Codice_Impianto_OK",
                             "Link_Impianto_OK",
                             "Pressione_Ingresso",
                             "Pressione_Ingresso_Min",
                             "Pressione_Ingresso_Max",
                             "Pressione_Ingresso_OK",
                             "Temperatura_Ingresso",
                             "Temperatura_Ingresso_Min",
                             "Temperatura_Ingresso_Max",
                             "Temperatura_Ingresso_OK",
                             "Pressione_Uscita",
                             "Pressione_Uscita_Min",
                             "Pressione_Uscita_Max",
                             "Pressione_Uscita_OK",
                             "Antisgocc_OK",
                             "AntisgoccPeriodoControllo",
                             "AntisgoccNpartenze",
                             "AntisgoccDurataPartenza",
                             "AlarmPump_1",
                             "AlarmPump_2",
                             "AlarmPump_3",
                             "AlarmPump_4",
                             "AlarmPump_5",
                             "AlarmPump_6",
                             "START_pompa_1",
                             "START_pompa_2",
                             "START_pompa_3",
                             "START_pompa_4",
                             "START_pompa_5",
                             "START_pompa_6"]
            for element in settings_list:
                t = (element, "0")
                records.append(t)
            self.execute_many(insert_query, records)
        self.close()
        logging.info("Initialization completed.")

    def load_settings(self):
        query = "SELECT * FROM settings"
        self.connect()
        self.execute(query)
        for setting in self.cursor.fetchall():
            self.settings[setting[0]] = setting[1]
        self.close()
        logging.info("Settings loaded.")

    def get_setting(self, key):
        query = "SELECT value FROM settings WHERE key = ?"
        self.connect()
        self.execute(query, (key,))
        result = self.cursor.fetchone()[0]
        self.close()
        return result

    def update_setting(self, key, value):
        self.settings[key] = [value]
        query = "UPDATE settings SET value = ? WHERE key = ?"
        self.connect()
        value = "{}".format(value)
        self.execute(query, (value, key))
        self.close()