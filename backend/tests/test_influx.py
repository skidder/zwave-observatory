"""Counter-reset delta flooring and CSV parsing tests."""
from app.influx import compute_deltas, parse_annotated_csv


def test_deltas_and_reset_flooring():
    points = [{"_value": 100, "_time": "t1"},
              {"_value": 110, "_time": "t2"},
              {"_value": 5, "_time": "t3"},     # reset: 5 < 110 -> floored, annotated
              {"_value": 25, "_time": "t4"}]
    out = compute_deltas(points)
    assert out[0]["delta"] == 0 and out[0]["reset"] is False
    assert out[1]["delta"] == 10 and out[1]["reset"] is False
    assert out[2]["delta"] == 0 and out[2]["reset"] is True
    assert out[3]["delta"] == 20 and out[3]["reset"] is False


def test_parse_annotated_csv():
    csv = '''#group,false,false,true,true,false,false,true,true,true,true
#datatype,string,long,dateTime:RFC3339,double,string,string,double,double,double,double
#default,_result,,,,,,,,
,result,table,_time,_value,_field,_measurement,node_id,rx,dropped,timeout
,,0,2026-11-11T00:00:00Z,42,commandsRX,zwave_frames,5,200,25,7
,,0,2026-11-11T01:00:00Z,58,commandsRX,zwave_frames,5,220,30,9

'''
    rows = parse_annotated_csv(csv)
    assert len(rows) == 2
    assert rows[0]["_value"] == "42"
    assert rows[1]["node_id"] == "5"
    assert rows[0]["_measurement"] == "zwave_frames"
