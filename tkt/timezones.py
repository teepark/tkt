'''
provide to_utc(datetime)->datetime and to_local(datetime)->datetime
the purpose is to enable all code to dump datetime objects to yaml in UTC time
and load them into local time
'''
import datetime
import time


_to_utc_offset = datetime.timedelta(0, time.timezone)

def to_utc(dt):
    return dt + _to_utc_offset

def to_local(dt):
    return dt - _to_utc_offset
