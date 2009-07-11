import datetime
import math


def to_utc_offset():
    herenow = datetime.datetime.now()
    utcnow = datetime.datetime.utcnow()
    seconds = int(10 * math.floor((utcnow - herenow).seconds / 10.0))
    return datetime.timedelta(0, seconds)

to_utc_offset = to_utc_offset()
to_local_offset = -to_utc_offset

def to_utc(dt):
    return dt + to_utc_offset

def to_local(dt):
    return dt + to_local_offset
