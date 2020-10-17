from time import perf_counter, sleep
from picandb.settingsmanager import SettingsManager


# TODO proper class conversion
def time_increase(seconds, minutes, hours):
    """
    Takes hours, minutes and seconds and increases them by one second.
    :param seconds: the second
    :param minutes: the minute
    :param hours: the hour count (can be over 24)
    :return: the increased time as seconds, minutes and hours
    """
    seconds += 1
    if seconds == 60:
        minutes += 1
        seconds = 0
    if minutes == 60:
        hours += 1
        minutes = 0
    return seconds, minutes, hours


def time_updater(reset=0):
    # This process will take care of updating the many time
    # variables in the database. Since database access time
    # may be significant, and an high-precision clock is needed
    # in order to avoid time drifts, perf_counter() will be used
    # sleep() will be considered "not precise"
    settings = SettingsManager("piCANclient.db")
    tl_limit = int(settings.get_setting("impianto_TL_Counter_SetCounter"))
    bk_limit = int(settings.get_setting("impianto_BK_Counter_SetCounter"))
    rb_limit = int(settings.get_setting("impianto_RB_Counter_SetCounter"))
    run = int(settings.get_setting("Operator_Pump_start"))
    start_time = perf_counter()
    while True:
        if reset == 1:
            # TODO wait until reset is 0
            end_time = perf_counter()
            remaining_time = 1 - (end_time - start_time)
            sleep(remaining_time)
            start_time = perf_counter()

        if run == 1 and reset == 0:

            rb_hour = int(settings.get_setting("impianto_RB_Counter_hour"))
            rb_min = int(settings.get_setting("impianto_RB_Counter_min"))
            rb_seconds = int(settings.get_setting("impianto_RB_Counter_sec"))
            if rb_hour < rb_limit:
                rb_seconds, rb_min, rb_hour = time_increase(rb_seconds, rb_min, rb_hour)
                if rb_hour >= rb_limit:
                    settings.update_setting("impianto_RB_SERVICE", 1)

            bk_hour = int(settings.get_setting("impianto_BK_Counter_hour"))
            bk_min = int(settings.get_setting("impianto_BK_Counter_min"))
            bk_seconds = int(settings.get_setting("impianto_BK_Counter_sec"))
            if bk_hour < bk_limit:
                bk_seconds, bk_min, bk_hour = time_increase(bk_seconds, bk_min, bk_hour)
                if bk_hour >= bk_limit:
                    settings.update_setting("impianto_BK_SERVICE", 1)

            tl_hour = int(settings.get_setting("impianto_TL_Counter_hour"))
            tl_min = int(settings.get_setting("impianto_TL_Counter_min"))
            tl_seconds = int(settings.get_setting("impianto_TL_Counter_sec"))
            if tl_hour < tl_limit:
                tl_seconds, tl_min, tl_hour = time_increase(tl_seconds, tl_min, tl_hour)
                if tl_hour >= tl_limit:
                    settings.update_setting("impianto_TL_SERVICE", 1)

            settings.update_setting("impianto_RB_Counter_hour", rb_hour)
            settings.update_setting("impianto_RB_Counter_min", rb_min)
            settings.update_setting("impianto_RB_Counter_sec", rb_seconds)

            settings.update_setting("impianto_BK_Counter_hour", bk_hour)
            settings.update_setting("impianto_BK_Counter_min", bk_min)
            settings.update_setting("impianto_BK_Counter_sec", bk_seconds)

            settings.update_setting("impianto_TL_Counter_hour", tl_hour)
            settings.update_setting("impianto_TL_Counter_min", tl_min)
            settings.update_setting("impianto_TL_Counter_sec", tl_seconds)

        run = int(settings.get_setting("Operator_Pump_start"))

        # Higher precision delay implementation
        end_time = perf_counter()
        remaining_time = 1-(end_time-start_time)
        sleep(remaining_time)
        start_time = perf_counter()
