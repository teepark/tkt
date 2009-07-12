import datetime

# cutoffs
_twomin = datetime.timedelta(0, 120)
_twohours = datetime.timedelta(0, 7200)
_twodays = datetime.timedelta(2)
_twoweeks = datetime.timedelta(14)
_sevenweeks = datetime.timedelta(49)

def since(fromtime):
    now = datetime.datetime.now()
    diff = now - fromtime

    if diff < _twomin:
        return "moments"

    if diff < _twohours:
        return "%d minutes" % (diff.seconds // 60)

    if diff < _twodays:
        return "%d hours" % (diff.seconds // 3600)

    if diff < _twoweeks:
        return "%d days" % diff.days

    if diff < _sevenweeks:
        return "%d weeks" % (diff.days // 7)

    months = (now.year - fromtime.year) * 12 + now.month - fromtime.month

    if months < 49:
        return "%d months" % months

    return "%d years" % (
            now.year - fromtime.year - (fromtime.month > now.month))
