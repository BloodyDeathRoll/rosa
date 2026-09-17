import re,collections,sys
REG={'us-west':['46042','46026','46022','46059','46218','46225'],'us-east':['41008','41013','44013'],'hawaii':['51201','51202','51205'],'portugal':['Faro-coast-buoy','Leixoes-coast-buoy','Sines-coast-buoy']}
B2R={b:r for r,bs in REG.items() for b in bs}
LEADS=['0-1d','1-3d','3-4d','4-5d','5-7d','7-9d','9d+']
def parse(f):
    out={};b=None
    for l in open(f):
        m=re.match(r'lead-time skill vs buoy (\S+)',l)
        if m: b=m.group(1); continue
        m=re.match(r'\s+(\S+)\s+(Sig\. wave height|Peak period|Mean per\. vs APD|Wave direction|Wind speed|Wind direction)\s+(\d+)\s+(\S+?)(m/s|m|s|°)\s+([\d.]+)',l)
        if m and b: out[(b,m.group(1),m.group(2))]=(int(m.group(3)),float(m.group(4)),float(m.group(6)))
    return out
arms={a:parse(a+'.txt') for a in ['om','gfswave','ecmwf','blend']}
def pooled(arm,var,lead,bs):
    n=s=0
    for b in bs:
        v=arms[arm].get((b,lead,var))
        if v: n+=v[0]; s+=v[0]*v[2]
    return (n,s/n) if n else (0,None)
allb=list(B2R)
for var in ['Sig. wave height','Wave direction']:
    for name,bs in [('POOLED-15',allb)]+list(REG.items()):
        print(f'\n{var} MAE  {name}')
        print('lead  '+'  '.join(f'{a:>14}' for a in arms))
        for L in LEADS:
            row=[pooled(a,var,L,bs) for a in arms]
            if not any(r[0] for r in row): continue
            print(f'{L:5} '+'  '.join(f'{(r[1] if r[1] is not None else float("nan")):7.3f} n={r[0]:<5}' for r in row))
