#!/usr/bin/env python3
from multiprocessing import Process, Queue
import logging
from datetime import datetime
from pathlib import Path
from processes.canprocess import CanProcess
from processes.socketprocess import SocketProcess
from sim import Sim
import os
import configparser
from picandb.settingsmanager import SettingsManager


def create_config(cfg: configparser.ConfigParser):
    # Create config file programmatically
    # TODO load/create can bus, sim and other missing settings like port and address, apn, ...
    cfg['Dati impianto'] = {'Codice_Impianto': 'default'}
    cfg['Limiti temporali'] = \
        {'# Default impianto_TL_Counter_SetCounter': '4. Limite di ore giornaliere prima del blocco dei contatori TL',
         'impianto_TL_Counter_SetCounter': '4',
         '# Default impianto_RB_Counter_SetCounter': '720. Limite di ore totali prima del blocco dei contatori RB',
         'impianto_RB_Counter_SetCounter': '720',
         '# Default impianto_BK_Counter_SetCounter': '1080. Limite di ore totali prima del blocco dei contatori BK',
         'impianto_BK_Counter_SetCounter': '1080'}

    cfg['Soglie pressione'] = {
        '# Default Pressione_Uscita_Max': '110. Bar massimi al di sopra dei quali le pompe '
                                          'non partiranno in nessun caso',
        'Pressione_Uscita_Max': '110',
        '# Default Pressione_Ingresso_Min': '0. Bar minimi al di sotto dei quali le pompe non partiranno.',
        'Pressione_Ingresso_Min': '0',
        '# Default Pressione_Ingresso_Max': '100. Bar massimi al di sopra dei quali le pompe non partiranno',
        'Pressione_Ingresso_Max': '100',
        }

    cfg['Antisgocciolamento'] = {
        '# Default AntisgoccPeriodoControllo': '3600. Secondi prima che il contatore del numero di partenze si resetti',
        'AntisgoccPeriodoControllo': '3600',
        '# Default AntisgoccNpartenze': "20. Numero di partenze entro AntisgoccPeriodoControllo "
                                        "per cui si attiva l'antisgocciolamento",
        'AntisgoccNpartenze': '20',
        '# Default AntisgoccDurataPartenze': '30. Numero minimo di secondi in cui una pompa '
                                             'deve restare accesa affinchè una partenza sia conteggiata',
        'AntisgoccDurataPartenze': '30'}
    cfg['CANBus'] = {
        '# Default bitrate': '500000. Bitrate in kbps della rete CANBus',
        'bitrate': '500000',
        '# Default interface_name:': 'can0. Default name of the CANBus interface',
        'interface_name': 'can0',
        '# Default bustype': 'socketcan. Socket type for the connection.'
                             ' On linux-based systems, it should be socketcan',
        'bustype': 'socketcan'
    }
    with open('settings.cfg', 'w', encoding='utf-8') as configfile:
        cfg.write(configfile)


def main():
    # Two separate queues will allow IPC
    # The can_interface_process will put on can_to_socket_queue
    # results and information. It will get from socket_to_can_queue
    # commands to be executed.
    # The socket_interface_process will put on socket_to_can_queue
    # commands received from the socket. It will read from
    # can_to_socket_queue the results and the information and
    # send them to the server via the socket
    # TODO: test CAN functionality (special equipment needed!)
    # TODO: implement backup database functionality
    # WARNING: database exceptions are not catched, as there should be none!

    # Prepare the logger
    now = datetime.now()
    directory = Path("logs/")
    filename = now.strftime("%Y-%m-%d_%H-%M-%S")
    filename += "_piCANcontroller.log"
    filename = directory / filename
    logging.basicConfig(level=logging.INFO, filename=filename, format="[%(asctime)s][%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)
    logger.info("Logger ready")

    # Prepare the database
    logger.info("Checking database state")
    settings = SettingsManager("piCANclient.db")
    old_imei = settings.get_setting("IMEI_impianto")

    # Create/Load the settings
    c = configparser.ConfigParser()
    if not os.path.exists('settings.cfg'):
        create_config(c)
    c.read('settings.cfg')
    installation_code = c['Dati impianto']['Codice_Impianto']
    tl_limit = c['Limiti temporali']['impianto_TL_Counter_SetCounter']
    rb_limit = c['Limiti temporali']['impianto_RB_Counter_SetCounter']
    bk_limit = c['Limiti temporali']['impianto_BK_Counter_SetCounter']
    max_outlet_pressure = c['Soglie pressione']['Pressione_Uscita_Max']
    min_inlet_pressure = c['Soglie pressione']['Pressione_Ingresso_Min']
    max_inlet_pressure = c['Soglie pressione']['Pressione_Ingresso_Max']
    anti_drip_time_limit = c['Antisgocciolamento']['AntisgoccPeriodoControllo']
    anti_drip_start_count_limit = c['Antisgocciolamento']['AntisgoccNpartenze']
    anti_drip_min_period = c['Antisgocciolamento']['AntisgoccDurataPartenze']
    can_bitrate = int(c['CANBus']['bitrate'])
    can_interface_name = c['CANBus']['interface_name']
    can_bustype = c['CANBus']['bustype']
    settings.update_setting('Codice_Impianto', installation_code)
    settings.update_setting('impianto_TL_Counter_SetCounter', tl_limit)
    settings.update_setting('impianto_RB_Counter_SetCounter', rb_limit)
    settings.update_setting('impianto_BK_Counter_SetCounter', bk_limit)
    settings.update_setting('Pressione_Uscita_Max', max_outlet_pressure)
    settings.update_setting('Pressione_Ingresso_Min', min_inlet_pressure)
    settings.update_setting('Pressione_Ingresso_Max', max_inlet_pressure)
    settings.update_setting('AntisgoccPeriodoControllo', anti_drip_time_limit)
    settings.update_setting('AntisgoccNpartenze', anti_drip_start_count_limit)
    settings.update_setting('AntisgoccDurataPartenze', anti_drip_min_period)

    logger.info("Preparing GSM modem")
    sim = Sim()
    if sim.connected.is_set():
        sim.disconnect()
    new_imei = sim.get_imei()
    sim.connect()

    # If the old imei is the default, then replace it.
    # If the old imei is not the default and the new is different,
    # the modem has been replaced, so an exception is raised
    if old_imei == settings.DEFAULT_IMEI:
        settings.update_setting("IMEI_impianto", new_imei)
    elif new_imei != old_imei:
        settings.update_setting("IMEI_impianto_OK", 0)
        logger.error("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
        raise IOError("Modem IMEI has changed unexpectedly. Reset the database or plug in the old modem")
    settings.update_setting("IMEI_impianto_OK", 1)
    imei = new_imei

    can_to_socket_queue = Queue()
    socket_to_can_queue = Queue()
    can_process = CanProcess(socket_to_can_queue, can_to_socket_queue,
                             bitrate=can_bitrate, interface_name=can_interface_name,
                             bustype=can_bustype)
    socket_process = SocketProcess(can_to_socket_queue, socket_to_can_queue, imei, sim)

    can_process.start()
    socket_process.start()

    # Nothing else needs to be done
    socket_process.join()
    can_process.join()


if __name__ == "__main__":
    main()
