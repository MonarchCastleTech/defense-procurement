from datetime import date
from pipeline.procurement_warning_model import band, clamp, robust_z, velocity, weekly

def test_clamp_bounds():
    assert clamp(-2)==0 and clamp(105)==100

def test_bands():
    assert [band(x) for x in (0,25,45,65,80)]==["BASELINE","WATCH","ELEVATED","HIGH","SEVERE"]

def test_robust_z_positive_outlier():
    assert robust_z(10,[1,1,2,2,3,3])>3

def test_weekly_bins():
    rows=[(date(2026,8,28),2),(date(2026,8,20),3),(date(2026,7,1),9)]
    bins=weekly(rows,date(2026,8,28))
    assert bins[0]==2 and bins[1]==3 and sum(bins)==14

def test_velocity_is_bounded():
    score,z=velocity(100,[1]*12,2)
    assert 0<=score<=100 and z==0

def test_velocity_rises_with_density():
    low,_=velocity(1,[1,2,1,2,1,2],2)
    high,_=velocity(10,[1,2,1,2,1,2],2)
    assert high>low
