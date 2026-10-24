# -*- coding: utf-8 -*-
"""Generic  multi-day activity optimizer (SciPy HiGHS MILP).

This engine is embedded in the HTML-exported standalone Python program.
It expects a CONFIG dictionary describing rules; no fixed event names/rates.
Requires: numpy, scipy (pip install numpy scipy).
"""
import sys
import time
from collections import defaultdict
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix


def run_model(cfg, route, scenario, objective='jade', jade_cap=None, time_limit=90):
    nd = int(cfg['days'])
    g = cfg['rules']
    thresholds = [x for x in cfg['tiers'] if x['boxes'] > 0]
    thresholds.sort(key=lambda x: x['points'])
    K = len(thresholds)
    delta = [t['boxes'] - (thresholds[i-1]['boxes'] if i else 0) for i,t in enumerate(thresholds)]
    max_box = sum(delta)*nd + sum(int(p.get('extra_boxes',0))*int(p['limit'])*(nd if p['limit_type']=='daily' else 1) for p in cfg['packs'])
    gem_limit = int(cfg['diamond']['daily_cap']) if cfg['diamond']['daily_cap'] is not None else 0
    gem_cost = float(cfg['diamond']['unit_cost'] or 0)
    exchange = [x for x in cfg.get('exchanges',[]) if x.get('limit') is not None and x['from_qty']>0 and x['to_qty']>0]
    packs = cfg['packs']

    names=[]; lower=[]; upper=[]; jade=[]; yuan=[]; integer=[]
    def variable(name, cap, j=0, r=0, lo=0):
        q=len(names); names.append(name);lower.append(lo);upper.append(cap)
        jade.append(float(j)); yuan.append(float(r));integer.append(1)
        return q
    day_vars=[]
    for d in range(nd):
        dv={'pack':[], 'gem':variable(f'd{d+1}.diamond_coins',gem_limit),
            'draw':variable(f'd{d+1}.draw',100000),
            'exchange':[],
            'tier':[variable(f'd{d+1}.tier{k+1}',1) for k in range(K)],
            'open':[variable(f'd{d+1}.open_stage{k}',max_box) for k in range(K+1)]}
        for pi,p in enumerate(packs):
            cap=int(p['limit'])
            if p['kind']=='coin_pack' and route=='B':cap=0
            if p['kind']=='target_pack' and route=='A':cap=0
            if d+1 < int(p.get('unlock_day',1)):cap=0
            dv['pack'].append(variable(f'd{d+1}.pack{pi}.{p["name"]}',cap,p['jade'],p['yuan']))
        for ei,x in enumerate(exchange):
            dv['exchange'].append(variable(f'd{d+1}.exchange{ei}',int(x['limit'])))
        day_vars.append(dv)
    rows=[]; low=[]; high=[]; labels=[]
    def add(expr, lo=-np.inf, hi=np.inf, label=''):
        rows.append({k:v for k,v in expr.items() if abs(v)>1e-9});low.append(lo);high.append(hi);labels.append(label)
    def plus(*parts):
        c=defaultdict(float)
        for e in parts:
            for k,v in e.items():c[k]+=v
        return dict(c)
    def mult(expr, factor):return {k:v*factor for k,v in expr.items()}
    def pack_expr(d, field):
        return {ix:float(p.get(field,0)) for ix,p in zip(day_vars[d]['pack'],packs) if p.get(field,0)}
    def gem_expr(d):return {day_vars[d]['gem']:1}
    def coin_gain(d):return plus(gem_expr(d),pack_expr(d,'coin_qty'))
    def target_direct(d):return pack_expr(d,'target_qty')
    def paid_boxes(d):return pack_expr(d,'extra_boxes')
    def exchange_expr(d, mode):
        return {ix:float(x[mode]) for ix,x in zip(day_vars[d]['exchange'],exchange)}
    def earned_boxes(d, count=K):
        return {day_vars[d]['tier'][i]:float(delta[i]) for i in range(count)}
    def opens(d,count=None):
        return {ix:1.0 for ix in day_vars[d]['open'][:count]}
    def free(d):return float(scenario[d])

    # Per-activity package and exchange limits. Per-day upper bounds already set.
    for pi,p in enumerate(packs):
        if p['limit_type']=='activity':
            add({dv['pack'][pi]:1 for dv in day_vars},hi=int(p['limit']),label='activity limit '+p['name'])
    for ei,x in enumerate(exchange):
        add({dv['exchange'][ei]:1 for dv in day_vars},hi=int(x['limit']),label='exchange limit '+str(ei))
    if cfg['diamond'].get('total_budget') is not None:
        add({dv['gem']:gem_cost for dv in day_vars},hi=float(cfg['diamond']['total_budget']),label='total diamond budget')
    # Prefix stock conservation; stage-wise box availability and tier threshold.
    for d,dv in enumerate(day_vars):
        coin_expr=plus(*[{day_vars[i]['draw']:1} for i in range(d+1)],
                       mult(plus(*[coin_gain(i) for i in range(d+1)]),-1))
        add(coin_expr,hi=sum(free(i) for i in range(d+1)),label=f'coin stock day{d+1}')
        normal_stock=plus(*[exchange_expr(i,'from_qty') for i in range(d+1)],
                          {day_vars[i]['draw']:-float(g['draw_normal']) for i in range(d+1)})
        add(normal_stock,hi=0,label=f'normal stock day{d+1}')
        if K:
            for k in range(K-1):
                add({dv['tier'][k+1]:1,dv['tier'][k]:-1},hi=0,label=f'tier order {d+1},{k}')
            base = plus(mult(coin_gain(d),g['coin_points']),
                        mult(target_direct(d),g['target_points']),
                        mult(exchange_expr(d,'to_qty'),g['target_points']),
                        {dv['draw']:g['draw_points']})
            for k,threshold in enumerate(thresholds):
                expr=plus(base,
                          {ix:float(g['target_points'])*float(g['box_expected']) for ix in dv['open'][:k+1]},
                          {dv['tier'][k]:-float(threshold['points'])})
                add(expr,lo=-float(g['coin_points'])*free(d),label=f'tier threshold {d+1},{k}')
        prior_rewards=plus(*[earned_boxes(i) for i in range(d)]) if d else {}
        prior_purchased=plus(*[paid_boxes(i) for i in range(d)]) if d else {}
        prior_used=plus(*[opens(i) for i in range(d)]) if d else {}
        for k in range(K+1):
            stock=plus(prior_used,opens(d,k+1),
                       mult(prior_rewards,-1),mult(prior_purchased,-1),
                       mult(paid_boxes(d),-1),
                       mult(earned_boxes(d,k),-1))
            add(stock,hi=0,label=f'box stage stock {d+1},{k}')
    # Target in *expected resource quantity*, not reward points; exchanges to shop rewards
    # can be converted to their required quantity upstream, if prerequisites confirmed.
    out=plus(*[target_direct(d) for d in range(nd)],
             *[exchange_expr(d,'to_qty') for d in range(nd)],
             {day_vars[d]['draw']:float(g['draw_target']) for d in range(nd)},
             *[{ix:float(g['box_expected']) for ix in day_vars[d]['open']} for d in range(nd)])
    add(out,lo=float(cfg['target']),label='final target')
    jade_expr={j:cost for j,cost in enumerate(jade) if cost}
    if jade_cap is not None:
        add(jade_expr,lo=float(jade_cap)-1e-7,hi=float(jade_cap)+1e-7,label='fix optimal jade')
    ri=[];ci=[];vv=[]
    for i,expr in enumerate(rows):
        for idx,coefficient in expr.items():ri.append(i);ci.append(idx);vv.append(coefficient)
    matrix=coo_matrix((vv,(ri,ci)),shape=(len(rows),len(names))).tocsr()
    obj = np.asarray(jade if objective=='jade' else yuan,float)
    t0=time.time()
    res=milp(obj,integrality=np.asarray(integer,int),bounds=Bounds(lower,upper),
             constraints=LinearConstraint(matrix,np.asarray(low),np.asarray(high)),
             options={'time_limit':float(time_limit),'mip_rel_gap':0.0})
    result={'route':route,'objective':objective,'status':int(res.status),'message':str(res.message),
            'time_sec':round(time.time()-t0,2),'bound':float(res.mip_dual_bound) if res.mip_dual_bound is not None else None,
            'gap':float(res.mip_gap) if res.mip_gap is not None else None,
            'solution':None}
    if res.x is None:return result
    x=np.rint(res.x).astype(int)
    # Independent check against all integer linear constraints (tolerance in expected resources).
    residue=np.asarray(matrix @ x,dtype=float)
    errors=[labels[i] for i in range(len(rows)) if (residue[i]<low[i]-0.0001 or residue[i]>high[i]+0.0001)]
    if errors:raise AssertionError('Independent constraint violation: '+str(errors[:12]))
    answer=[]; coins_left=boxes_left=norm_left=adv_left=0.0
    for d,dv in enumerate(day_vars):
        buy=[(p['name'],int(x[j])) for p,j in zip(packs,dv['pack']) if x[j]]
        earned_coin=free(d)+x[dv['gem']]+sum(x[j]*p['coin_qty'] for p,j in zip(packs,dv['pack']))
        direct=sum(x[j]*p['target_qty'] for p,j in zip(packs,dv['pack']))
        fund_boxes=sum(x[j]*p['extra_boxes'] for p,j in zip(packs,dv['pack']))
        exchange_count=[int(x[j]) for j in dv['exchange']]
        converted=sum(n*exc['to_qty'] for n,exc in zip(exchange_count,exchange))
        used_norm=sum(n*exc['from_qty'] for n,exc in zip(exchange_count,exchange))
        draw=int(x[dv['draw']]); stage_open=[int(x[j]) for j in dv['open']]
        levels=[int(x[j]) for j in dv['tier']]
        new_boxes=sum(k*n for k,n in zip(delta,levels))
        points_before=earned_coin*g['coin_points']+direct*g['target_points']+converted*g['target_points']+draw*g['draw_points']
        points_final=points_before+sum(stage_open)*g['target_points']*g['box_expected']
        coins_left+=earned_coin-draw;boxes_left+=fund_boxes+new_boxes-sum(stage_open)
        norm_left+=draw*g['draw_normal']-used_norm
        adv_left+=direct+converted+draw*g['draw_target']+sum(stage_open)*g['box_expected']
        answer.append({'day':d+1,'packs':buy,'free_coin':free(d),'diamond_coin':int(x[dv['gem']]),
                'new_coin':round(earned_coin,6),'draw':draw,'end_coin':round(coins_left,6),
                'exchange':exchange_count,'end_normal':round(norm_left,6),
                'tier_flags':levels,'new_tier_boxes':new_boxes,'pack_boxes':fund_boxes,
                'opened_phases':stage_open,'end_boxes':round(boxes_left,6),
                'points_before_boxes':round(points_before,6),'points_final':round(points_final,6),
                'direct_target':direct,'converted_target':converted,'end_target':round(adv_left,6)})
    result['solution']={'jade':round(float(x@np.asarray(jade)),4),'yuan':round(float(x@np.asarray(yuan)),4),
        'diamond_used':sum(v['diamond_coin']*gem_cost for v in answer),'expected_target':round(adv_left,9),
        'days':answer,'violations':errors}
    return result


def solve_config(CONFIG):
    print('Game:',CONFIG.get('game'),'Target:',CONFIG.get('target'),CONFIG['names']['target'])
    print('Assumptions:', ' | '.join(CONFIG.get('assumptions',[])))
    limit=CONFIG.get('time_limit',90)
    all_results=[]
    for sc in CONFIG['scenarios']:
        print('\nSCENARIO:',sc['name'])
        summary=[]
        for route in CONFIG.get('routes',['A','B','C']):
            one=run_model(CONFIG,route,sc['coins'],'jade',time_limit=limit)
            if not one['solution']:
                print('ROUTE',route,'no feasible incumbent',one['message'])
                summary.append(one);continue
            if one['status']==0:
                two=run_model(CONFIG,route,sc['coins'],'yuan',jade_cap=one['solution']['jade'],time_limit=limit)
                chosen=two if two['solution'] else one
            else:
                chosen=one
            chosen['first_pass_status']=one['status'];chosen['first_pass_gap']=one['gap'];chosen['first_pass_bound']=one['bound']
            summary.append(chosen)
            sol=chosen['solution']
            cert=(one['status']==0 and chosen['status']==0)
            print(f"ROUTE {route}: jade={sol['jade']}, CNY={sol['yuan']}, expected={sol['expected_target']}, diamond={sol['diamond_used']}; certified={cert}, gap={chosen['gap']}")
        valid=[r for r in summary if r['solution']]
        if not valid:
            print('No feasible solution found for this scenario (not necessarily infeasible).');continue
        best=min(valid,key=lambda r:(r['solution']['jade'],r['solution']['yuan']))
        certified=(best.get('first_pass_status')==0 and best['status']==0)
        print('BEST ROUTE:',best['route'],'CERTIFIED OPTIMAL' if certified else 'FEASIBLE CANDIDATE ONLY')
        for day in best['solution']['days']:
            print('DAY',day['day'], 'packs',day['packs'],'free',day['free_coin'],'diamond',day['diamond_coin'],
                'coin gain',day['new_coin'],'draw',day['draw'],'coin left',day['end_coin'],
                'convert',day['exchange'],'tiers',day['tier_flags'],'new boxes',day['new_tier_boxes'],
                'fund boxes',day['pack_boxes'],'open by stage',day['opened_phases'],
                'remaining boxes',day['end_boxes'],'points',day['points_final'],'expected cumulative target',day['end_target'])
        all_results.append((sc['name'],summary))
    return all_results

if __name__=='__main__':
    if 'CONFIG' not in globals():
        import json
        if len(sys.argv)<2:
            sys.exit('Usage: python 通用游戏活动_MILP求解引擎_v13.py event.json')
        with open(sys.argv[1],encoding='utf-8') as f:CONFIG=json.load(f)
    solve_config(CONFIG)
