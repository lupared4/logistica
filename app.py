# -*- coding: utf-8 -*-
"""
Dashboard Log??stica ??? Flask App
Procesa BASEAPP.xlsb y genera m??tricas de inventario, vencimientos y ML Full.
"""
from flask import (Flask, render_template, request, redirect,
                   url_for, session, send_file, jsonify)
import pandas as pd
import numpy as np
import os, math, io, datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'cambia-esto-en-produccion')

DEFAULT_FILE = os.path.join(os.path.dirname(__file__), 'BASEAPP.xlsb')

# Credenciales cargadas desde .env  (USER_<nombre>=<contraseña>)
# Las claves se normalizan a minúsculas porque Windows uppercasea os.environ
USERS = {k[5:].lower(): v for k, v in os.environ.items() if k.startswith('USER_') and v}

# ?????? HELPERS ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def sf(v, d=0.0):
    """Safe float conversion."""
    try:
        if v is None:
            return d
        f = float(v)
        return d if math.isnan(f) else f
    except Exception:
        return d


def si(v, d=0):
    return int(sf(v, d))


def excel_date(serial):
    """Excel serial ??? DD/MM/YYYY string."""
    try:
        n = float(serial)
        if math.isnan(n):
            return ''
        dt = pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(n))
        return dt.strftime('%d/%m/%Y')
    except Exception:
        return str(serial) if serial else ''


def _col(df, *keys):
    """Return first matching column name, or None."""
    for k in keys:
        for c in df.columns:
            if k.upper() in str(c).upper():
                return c
    return None


def linear_regression_next(vals):
    """Return predicted next value from a list of numbers."""
    n = len(vals)
    if n < 2:
        return 0.0
    sx = sum(range(n))
    sy = sum(vals)
    sxy = sum(i * v for i, v in enumerate(vals))
    sxx = sum(i * i for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return max(0.0, slope * n + intercept)


def coef_var(vals):
    arr = [v for v in vals if v is not None]
    if not arr:
        return 0.0
    mean = sum(arr) / len(arr)
    if mean == 0:
        return 0.0
    std = math.sqrt(sum((v - mean) ** 2 for v in arr) / len(arr))
    return std / mean


def z_anomaly(vals):
    if len(vals) < 5:
        return False
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
    if std == 0:
        return False
    return abs((vals[-1] - mean) / std) > 2.5


# ?????? MOTOR PRINCIPAL ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
def procesar_baseapp(source, dias_cob=30, base_calc='vtasq60'):
    """Lee BASEAPP.xlsb/.xlsx y devuelve dict con todos los datos o {'error':...}"""
    try:
        import io as _io
        # Detectar nombre de archivo correctamente para FileStorage o path
        if hasattr(source, 'filename'):
            _fname = source.filename or ''
        elif hasattr(source, 'name'):
            _fname = os.path.basename(source.name)
        else:
            _fname = str(source)
        engine = 'pyxlsb' if _fname.lower().endswith('.xlsb') else 'openpyxl'
        # Envolver en BytesIO para FileStorage (upload del usuario)
        if hasattr(source, 'read'):
            _buf = _io.BytesIO(source.read())
            xls = pd.ExcelFile(_buf, engine=engine)
        else:
            xls = pd.ExcelFile(source, engine=engine)
        available = xls.sheet_names

        def read(name, *alts):
            for n in (name,) + alts:
                if n in available:
                    df = pd.read_excel(xls, sheet_name=n, dtype=str)
                    df.columns = [str(c).strip() for c in df.columns]
                    return df
            return pd.DataFrame()

        df_grafana  = read('GRAFANA')
        df_pbi      = read('PBI')
        df_nomina   = read('NOMINA')
        df_ltime    = read('L TIME', 'LTIME')
        df_cargos   = read('CARGOS')
        df_sml      = read('STOCK ML')
        df_pml      = read('PLAN MIL', 'PLAN ML')
        df_venc     = read('VENCIMIENTO', 'VENCIMIENTOS')
        df_canasta  = read('CANASTA')
        df_mla      = read('BASE MLA')
        df_enviados = read('ENVIADOS')
        df_mercado  = read('MERCADO')
        df_simplex  = read('VTA SIMPLEX', 'VTAS SIMPLEX')
        df_sta19    = read('STA19')

        # ?????? NOMINA: Maestro de productos ???????????????????????????????????????????????????????????????????????????????????????????????????
        map_nomina = {}
        if not df_nomina.empty:
            # Saltar fila de cabecera interna si existe
            if 'cod_articu' in str(df_nomina.iloc[0].get('SKU', '')).lower():
                df_nomina = df_nomina.iloc[1:].reset_index(drop=True)
            for _, r in df_nomina.iterrows():
                sku = str(r.get('SKU', '')).strip().upper()
                if sku and sku not in ('SKU', 'NAN', 'PRUEBA', 'COD_ARTICU'):
                    map_nomina[sku] = {
                        'desc':       str(r.get('DESCRIPCION', '')).strip(),
                        'marca':      str(r.get('MARCA', '')).strip(),
                        'prov':       str(r.get('PROV', '')).strip(),
                        'perfil':     {'A':'Activo','V':'Inactivo','N':'NULL','C':'Combo'}.get(
                                          str(r.get('PERFIL','')).strip(),
                                          str(r.get('PERFIL','')).strip()),
                        'ean':        str(r.get('EAN', '')).strip(),
                        'uxb':        sf(r.get('UXB', 1), 1),
                        'sub_perfil': str(r.get('SUB PERFIL', '')).strip(),
                    }

        # Analista por SKU desde GRAFANA (usado en cargos, vencimientos, etc.)
        map_analista_sku = {}
        if not df_grafana.empty:
            for _, _r in df_grafana.iterrows():
                _s = str(_r.get('SKU', '')).strip().upper()
                _a = str(_r.get('Analista', _r.get('ANALISTA', ''))).strip()
                if _s and _a and _s != 'NAN':
                    map_analista_sku[_s] = _a

        # ?????? LEAD TIME ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_ltime = {}
        if not df_ltime.empty:
            pc = _col(df_ltime, 'PROV')
            lc = _col(df_ltime, 'LEAD')
            if pc and lc:
                for _, r in df_ltime.iterrows():
                    p = str(r[pc]).strip().upper()
                    if p:
                        map_ltime[p] = sf(r[lc], 7)

        # ?????? CANASTA: bloqueados ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_bloqueados = set()
        if not df_canasta.empty:
            sc = _col(df_canasta, 'SKU')
            fc = _col(df_canasta, 'BLOQ')
            if sc and fc:
                for _, r in df_canasta.iterrows():
                    val = str(r[fc]).strip().upper()
                    if val in ('SI', 'S??', 'S', '1'):
                        s = str(r[sc]).strip().upper()
                        if s:
                            map_bloqueados.add(s)

        # ?????? STA19: costo ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_costo = {}
        if not df_sta19.empty:
            sc = _col(df_sta19, 'SKU')
            cc = _col(df_sta19, 'PRECIO_LISTA_900', 'COSTO_COMPRA')
            if sc and cc:
                for _, r in df_sta19.iterrows():
                    s = str(r[sc]).strip().upper()
                    if s and s != 'NAN':
                        map_costo[s] = sf(r[cc])

        # ?????? CARGOS ML ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_cargos_sku = {}
        cargos_list = []
        if not df_cargos.empty:
            sc   = _col(df_cargos, 'SKU')
            fc   = _col(df_cargos, 'FECHA')
            uc   = _col(df_cargos, 'UNIDADES CON CARGO')
            ucc  = _col(df_cargos, 'CARGO POR UNIDAD')
            ac   = _col(df_cargos, 'ANTIG')
            tc   = _col(df_cargos, 'TOTAL CARGOS')
            dc   = _col(df_cargos, 'DESCRIPCION')
            if sc:
                latest = 0
                if fc:
                    latest = df_cargos[fc].apply(sf).max()
                for _, r in df_cargos.iterrows():
                    if fc and sf(r[fc]) != latest:
                        continue
                    sku = str(r[sc]).strip().upper()
                    if not sku or sku == 'NAN':
                        continue
                    u   = si(r[uc] if uc else 0)
                    ucu = si(r[ucc] if ucc else 0)
                    tot = si(r[tc] if tc else 0)
                    ant = str(r[ac] if ac else '').strip()
                    desc = str(r[dc] if dc else '').strip()
                    fstr = excel_date(r[fc]) if fc else ''
                    if sku not in map_cargos_sku:
                        map_cargos_sku[sku] = {'monto': 0, 'unidades': 0}
                    map_cargos_sku[sku]['monto']    += tot
                    map_cargos_sku[sku]['unidades'] += u
                    _nom_c = map_nomina.get(sku, {})
                    cargos_list.append({
                        'SKU': sku, 'DESCRIPCION': desc or _nom_c.get('desc', ''),
                        'MARCA': _nom_c.get('marca', ''),
                        'PROV': _nom_c.get('prov', ''),
                        'ANALISTA': map_analista_sku.get(sku, ''),
                        'ANTIGUEDAD': ant,
                        'UDS_CARGO': u, 'CARGO_UNIT': ucu,
                        'TOTAL': tot, 'FECHA': fstr,
                    })
            cargos_list.sort(key=lambda x: x['TOTAL'], reverse=True)

        # ?????? PLAN ML ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_planml = {}
        if not df_pml.empty:
            sc  = _col(df_pml, 'SKU')
            rc  = _col(df_pml, 'RECOMEND')
            sgc = _col(df_pml, 'SUGERIDAS', 'SUGERIDA')
            if sc:
                for _, r in df_pml.iterrows():
                    sku = str(r[sc]).strip().upper()
                    if sku and sku != 'NAN':
                        rec = str(r[rc] if rc else '').lower()
                        map_planml[sku] = {
                            'urgente': 'urgencia' in rec or 'perdiendo' in rec,
                            'sug': si(r[sgc] if sgc else 0),
                        }

        # ?????? STOCK ML ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_sml = {}
        ml_sin_stock = []
        if not df_sml.empty:
            sc    = _col(df_sml, 'SKU')
            fc    = _col(df_sml, 'UNIDADES EN FULL')
            vc30  = _col(df_sml, 'VENDIDAS EN 30')
            ic    = _col(df_sml, 'IMPULSAR')
            ec    = _col(df_sml, 'ESTADO')
            descc = _col(df_sml, 'DESCRIPCION')
            ag    = _col(df_sml, 'AGOTAR')
            if sc:
                for _, r in df_sml.iterrows():
                    sku = str(r[sc]).strip().upper()
                    if not sku or sku == 'NAN':
                        continue
                    full  = si(r[fc] if fc else 0)
                    vta30 = si(r[vc30] if vc30 else 0)
                    imp   = 'SI' in str(r[ic] if ic else '').upper()
                    map_sml[sku] = {'full': full, 'vta30': vta30, 'impulsar': imp, 'estado': str(r[ec] if ec else '').strip()}
                    if full == 0 and vta30 > 0:
                        ml_sin_stock.append({
                            'SKU': sku,
                            'DESCRIPCION': str(r[descc] if descc else '').strip(),
                            'FULL': 0, 'VTA30': vta30,
                            'AGOTAR': str(r[ag] if ag else '').strip(),
                            'ESTADO': str(r[ec] if ec else '').strip(),
                            'URGENTE': map_planml.get(sku, {}).get('urgente', False),
                            'SUG_FULL': map_planml.get(sku, {}).get('sug', 0),
                        })
            ml_sin_stock.sort(key=lambda x: x['VTA30'], reverse=True)

        # ?????? MLA lookup ?????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        map_mla = {}
        if not df_mla.empty:
            sc = _col(df_mla, 'SKU')
            mc = _col(df_mla, 'MLA')
            if sc and mc:
                for _, r in df_mla.iterrows():
                    s = str(r[sc]).strip().upper()
                    if s:
                        map_mla[s] = str(r[mc]).strip()

        # ?????? GRAFANA: Procesamiento multi-dep??sito ??????????????????????????????????????????????????????????????????
        if df_grafana.empty:
            return {'error': 'La solapa GRAFANA est?? vac??a o no se encontr??.'}

        day_cols = [c for c in df_grafana.columns
                    if str(c).lstrip('-').isdigit() and int(str(c)) < 0]

        sku_data = {}
        for _, r in df_grafana.iterrows():
            sku = str(r.get('SKU', '')).strip().upper()
            if not sku or sku in ('NAN', 'SKU', 'TOTAL'):
                continue

            dep      = str(r.get('Deposito', r.get('DEPOSITO', ''))).strip()
            stock    = sf(r.get('Stock', r.get('STOCK', 0)))
            vtasq60  = sf(r.get('VTASQ60', 0))
            vpd      = sf(r.get('VPD_Cpra', 0))
            compras  = sf(r.get('Compras', r.get('COMPRAS', 0)))
            prov_key = str(r.get('Prov', r.get('PROV', ''))).strip().upper()

            if sku not in sku_data:
                nom = map_nomina.get(sku, {})
                lt  = map_ltime.get(prov_key, 7)
                sku_data[sku] = {
                    'SKU':        sku,
                    'DESCRIPCION': nom.get('desc') or str(r.get('Descripcion', r.get('DESCRIPCION', ''))).strip(),
                    'MARCA':      nom.get('marca') or str(r.get('Marca', r.get('MARCA', ''))).strip(),
                    'PROV':       prov_key,
                    'ANALISTA':   str(r.get('Analista', r.get('ANALISTA', ''))).strip(),
                    'PERFIL':     str(r.get('Perfil', '')).strip() or nom.get('perfil', ''),
                    'EAN':        nom.get('ean', ''),
                    'UXB':        nom.get('uxb', 1),
                    'LEAD_TIME':  lt,
                    'STOCK_DEP1': 0, 'STOCK_DEP80': 0, 'STOCK_OTROS': 0,
                    'VTASQ60':    0, 'VPD': 0, 'COMPRAS_EC': 0,
                    'BLOQUEADO':  sku in map_bloqueados,
                    '_hist':      [],
                }

            d = sku_data[sku]
            if '80' in dep:
                d['STOCK_DEP80'] += stock
            elif dep in ('1', '01'):
                d['STOCK_DEP1'] += stock
            else:
                d['STOCK_OTROS'] += stock
            d['VTASQ60']   += vtasq60
            d['VPD']       += vpd
            d['COMPRAS_EC'] += compras
            if not d['_hist'] and day_cols:
                d['_hist'] = [sf(r.get(c, 0)) for c in day_cols[:60]]

        # ?????? PBI: completar stock por dep??sito ??????????????????????????????????????????????????????????????????????????????
        if not df_pbi.empty:
            sc    = _col(df_pbi, 'SKU')
            d1c   = 'DEP 1' if 'DEP 1' in df_pbi.columns else _col(df_pbi, 'DEP 1', 'DEP 01')
            d80c  = 'DEP 80' if 'DEP 80' in df_pbi.columns else _col(df_pbi, 'DEP 80')
            totc  = _col(df_pbi, 'TOTAL')
            descc = _col(df_pbi, 'DESCRIPCION')
            if sc:
                for _, r in df_pbi.iterrows():
                    sku = str(r[sc]).strip().upper()
                    if not sku or sku == 'NAN':
                        continue
                    d1  = sf(r[d1c] if d1c else 0)
                    d80 = sf(r[d80c] if d80c else 0)
                    tot = sf(r[totc] if totc else 0)
                    if sku not in sku_data:
                        nom = map_nomina.get(sku, {})
                        sku_data[sku] = {
                            'SKU': sku,
                            'DESCRIPCION': nom.get('desc') or str(r[descc] if descc else '').strip(),
                            'MARCA': nom.get('marca', ''), 'PROV': nom.get('prov', ''),
                            'ANALISTA': '', 'PERFIL': nom.get('perfil', ''),
                            'EAN': nom.get('ean', ''), 'UXB': nom.get('uxb', 1),
                            'LEAD_TIME': 7, 'VTASQ60': 0, 'VPD': 0, 'COMPRAS_EC': 0,
                            'BLOQUEADO': sku in map_bloqueados,
                            'STOCK_DEP1': d1, 'STOCK_DEP80': d80, 'STOCK_OTROS': 0,
                            '_hist': [],
                        }
                    else:
                        if sku_data[sku]['STOCK_DEP1'] == 0:
                            sku_data[sku]['STOCK_DEP1'] = d1
                        if sku_data[sku]['STOCK_DEP80'] == 0:
                            sku_data[sku]['STOCK_DEP80'] = d80
                    sku_data[sku]['STOCK_TOTAL_PBI'] = tot

        # ?????? M??tricas por SKU ??????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        items = []
        hist_map = {}
        for sku, d in sku_data.items():
            vta       = d['VTASQ60']
            stock_d1  = d['STOCK_DEP1']
            stock_d80 = d['STOCK_DEP80']
            stock_tot = d.get('STOCK_TOTAL_PBI',
                               stock_d1 + stock_d80 + d['STOCK_OTROS'])
            lt        = d['LEAD_TIME']
            costo     = map_costo.get(sku, 0)
            mla       = map_mla.get(sku, '')

            vta_d  = vta if vta > 0 else 0
            dias_s = round(stock_tot / vta_d) if vta_d > 0 else (999 if stock_tot > 0 else 0)
            ss     = 2.33 * vta_d * math.sqrt(lt) if vta_d > 0 else 0
            uxb    = max(1, int(d.get('UXB', 1) or 1))
            sug_raw = max(0, (vta_d * dias_cob + ss) - stock_tot)
            # Redondear la sugerencia al bulto (caja) más cercano hacia arriba
            import math as _math
            cant_bultos = int(_math.ceil(sug_raw / uxb)) if sug_raw > 0 else 0
            sug         = cant_bultos * uxb

            hist = d.pop('_hist', [])
            chrono = list(reversed(hist)) if hist else []
            hist_map[sku] = chrono
            if chrono:
                cv  = coef_var(chrono)
                ia  = round(linear_regression_next(chrono), 3)
                anom = z_anomaly(chrono)
                if vta_d == 0:    stab = 'Inactivo'
                elif cv < 0.3:    stab = 'Estable'
                elif cv < 0.7:    stab = 'Variable'
                else:             stab = 'Err??tico'
                n = len(chrono)
                vtasq45 = round(sum(chrono[-45:]) / min(45, n), 3)
                vtasq30 = round(sum(chrono[-30:]) / min(30, n), 3)
                vtasq15 = round(sum(chrono[-15:]) / min(15, n), 3)
            else:
                cv, ia, anom, stab = 0, 0, False, 'S/D'
                vtasq45 = vtasq30 = vtasq15 = 0.0

            sml_d = map_sml.get(sku, {})
            cargos_d = map_cargos_sku.get(sku, {})

            d.update({
                'STOCK_TOTAL': round(stock_tot),
                'COSTO':       round(costo, 2),
                'VTA_DIARIA':  round(vta_d, 3),
                'DIAS_STOCK':  min(dias_s, 999),
                'SUG_COMPRA':  sug,
                'CANT_BULTOS': cant_bultos,
                'UXB':         uxb,
                'STABILITY':   stab,
                'CV':          round(cv, 3),
                'VTA_IA':      ia,
                'ANOMALY':     anom,
                'ABC':         'C',   # se asigna despu??s
                'XYZ':         'Z',
                'ABC_XYZ':     'CZ',
                'QUIEBRE':     stock_tot == 0 and vta_d > 0,
                'CRITICO':     0 < dias_s <= 5 and vta_d > 0,
                'MLA':         mla,
                'ML_FULL':     sml_d.get('full', 0),
                'ML_VTA30':    sml_d.get('vta30', 0),
                'ML_URGENTE':  map_planml.get(sku, {}).get('urgente', False),
                'ML_SUG_FULL': map_planml.get(sku, {}).get('sug', 0),
                'CARGOS_MONTO': cargos_d.get('monto', 0),
                'ESTADO':      'Bloqueado' if d.get('BLOQUEADO') else ('Activo' if vta_d > 0 else 'Inactivo'),
                'ESTADO_ML':   sml_d.get('estado', ''),
                'VTA30':       round(vta_d * 30),
                'VTASQ60_IA':  round(ia * 60),
                'STOCK_SEG':   round(ss),
                'STOCK_MIN':   round(ss),
                'STOCK_MAX':   round(vta_d * dias_cob + ss),
                'DIAS_EST':    min(round(stock_tot / ia) if ia > 0 else min(dias_s, 999), 999),
                'SUB_PERFIL':  map_nomina.get(sku, {}).get('sub_perfil', ''),
                'EN_CAMINO':   si(d.get('COMPRAS_EC', 0)),
                'AGOT_EST':    ('AGOTADO' if dias_s <= 0 else ('\u221e' if dias_s >= 999 else (datetime.date.today() + datetime.timedelta(days=min(dias_s,730))).strftime('%d/%m/%Y'))),
                'VTASQ45':     vtasq45,
                'VTASQ30':     vtasq30,
                'VTASQ15':     vtasq15,
                'VPD_CPRA':    round(d.get('VPD', 0), 3),
                'VENTA_PERDIDA': round(vta_d * costo) if (vta_d > 0 and stock_tot == 0) else 0,
                'INVERSION':   round(sug * costo),
                'DISPONIBLE':  max(0, round(stock_d1 - ss)),
            })
            d.pop('STOCK_TOTAL_PBI', None)
            items.append(d)

        # ?????? ABC / XYZ ????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        items_s = sorted(items, key=lambda x: x['VTA_DIARIA'] * x['COSTO'], reverse=True)
        tot_v = sum(it['VTA_DIARIA'] * it['COSTO'] for it in items_s)
        acc = 0.0
        for it in items_s:
            acc += it['VTA_DIARIA'] * it['COSTO']
            pct = acc / tot_v if tot_v > 0 else 0
            it['ABC'] = 'A' if pct <= 0.80 else ('B' if pct <= 0.95 else 'C')
            xyz = 'X' if it['STABILITY'] == 'Estable' else (
                  'Y' if it['STABILITY'] == 'Variable' else 'Z')
            it['XYZ']     = xyz
            it['ABC_XYZ'] = it['ABC'] + xyz

        # ?????? VENCIMIENTOS ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        venc_list = []
        if not df_venc.empty:
            sc    = _col(df_venc, 'SKU')
            diasc = _col(df_venc, 'VENCIMIENTO REAL')
            fvc   = _col(df_venc, 'FECHA DE VENCIMIENTO')
            fic   = _col(df_venc, 'FECHA INGRESO', 'F. INGRESO', 'INGRESO')
            descc = _col(df_venc, 'DESCRIPCION')
            udsc  = _col(df_venc, 'UNIDADES')
            stotc = _col(df_venc, 'STOCK TOTAL')
            marc  = _col(df_venc, 'MARCA')
            provc = _col(df_venc, 'PROVEEDOR')
            _map_sdeps = {it['SKU']: (int(it.get('STOCK_DEP1', 0)), int(it.get('STOCK_DEP80', 0))) for it in items}
            if sc:
                for _, r in df_venc.iterrows():
                    sku = str(r[sc]).strip().upper()
                    if not sku or sku == 'NAN':
                        continue
                    dias = si(r[diasc] if diasc else 999)
                    uds  = si(r[udsc] if udsc else 0)
                    costo_v = map_costo.get(sku, 0)
                    riesgo  = round(uds * costo_v) if dias <= 30 else 0
                    _d1, _d80 = _map_sdeps.get(sku, (0, 0))
                    nom_v = map_nomina.get(sku, {})
                    venc_list.append({
                        'SKU':              sku,
                        'DESCRIPCION':      str(r[descc] if descc else '').strip() or nom_v.get('desc', ''),
                        'MARCA':            str(r[marc] if marc else '').strip() or nom_v.get('marca', ''),
                        'PROVEEDOR':        str(r[provc] if provc else '').strip() or nom_v.get('prov', ''),
                        'FECHA_INGRESO':    excel_date(r[fic]) if fic else '',
                        'FECHA_VENC':       excel_date(r[fvc]) if fvc else '',
                        'DIAS_VENC':        dias,
                        'UNIDADES':         uds,
                        'STOCK_TOTAL':      si(r[stotc] if stotc else 0),
                        'RIESGO_MONETARIO': riesgo,
                        'DEP1':             _d1,
                        'DEP80':            _d80,
                        'ANALISTA':         map_analista_sku.get(sku, ''),
                    })
            venc_list.sort(key=lambda x: x['DIAS_VENC'])

        # ?????? ENVIADOS ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        enviados_list = []
        if not df_enviados.empty:
            sc   = _col(df_enviados, 'SKU')
            fc   = _col(df_enviados, 'FECHA')
            descc= _col(df_enviados, 'DESCRIPCI')
            pc   = _col(df_enviados, 'PROV')
            mc   = _col(df_enviados, 'MARCA')
            cc   = _col(df_enviados, 'ENVIO REALIZADO')
            ctc  = _col(df_enviados, 'COSTO TOTAL')
            nc   = _col(df_enviados, 'NUM ENVIO', 'N ENVIO', 'N ENV', 'NRO ENV', 'NUMERO', 'N°')
            if sc:
                for _, r in df_enviados.iterrows():
                    sku = str(r[sc]).strip().upper()
                    if not sku or sku == 'NAN':
                        continue
                    enviados_list.append({
                        'FECHA':       excel_date(r[fc]) if fc else '',
                        'SKU':         sku,
                        'DESCRIPCION': str(r[descc] if descc else '').strip(),
                        'PROV':        str(r[pc] if pc else '').strip(),
                        'MARCA':       str(r[mc] if mc else '').strip(),
                        'CANT':        si(r[cc] if cc else 0),
                        'COSTO_TOTAL': si(r[ctc] if ctc else 0),
                        'NUM_ENVIO':   str(r[nc] if nc else '').strip(),
                    })
            enviados_list.sort(key=lambda x: x['FECHA'], reverse=True)
        enviados_sku = {}
        for _e in enviados_list:
            enviados_sku[_e['SKU']] = enviados_sku.get(_e['SKU'], 0) + _e['CANT']

        # ?????? VENTAS MERCADO y SIMPLEX ???????????????????????????????????????????????????????????????????????????????????????????????????
        def proc_ventas(df):
            res = []
            if df.empty:
                return res
            mc  = _col(df, 'MES')
            mac = _col(df, 'MARCA')
            fc  = _col(df, 'FACTURACION')
            uc  = _col(df, 'UNIDADES')
            if not (mc and mac and fc):
                return res
            for _, r in df.iterrows():
                marca = str(r[mac]).strip()
                if not marca or marca in ('0', 'nan', 'NAN'):
                    continue
                mes_raw = r[mc]
                mes_str = excel_date(mes_raw) if str(mes_raw).replace('.', '').isdigit() else str(mes_raw)
                res.append({
                    'MES': mes_str, 'MARCA': marca,
                    'FACTURACION': sf(r[fc]), 'UNIDADES': si(r[uc] if uc else 0),
                })
            return res

        ventas_mercado = proc_ventas(df_mercado)
        ventas_simplex = proc_ventas(df_simplex)

        # Consolidar por marca para gr??fico
        mercado_by_marca = {}
        for v in ventas_mercado:
            m = v['MARCA']
            mercado_by_marca[m] = mercado_by_marca.get(m, 0) + v['FACTURACION']
        top_marcas = sorted(mercado_by_marca.items(), key=lambda x: x[1], reverse=True)[:15]

        # ?????? KPIs ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
        activos    = [it for it in items if it['VTA_DIARIA'] > 0]
        quiebres   = [it for it in activos if it['QUIEBRE']]
        criticos   = [it for it in activos if it['CRITICO']]
        valor_inv  = sum(it['STOCK_TOTAL'] * it['COSTO'] for it in items)
        tot_cargos = sum(v.get('monto', 0) for v in map_cargos_sku.values())
        venc_venc  = sum(1 for v in venc_list if v['DIAS_VENC'] < 0)
        venc_30    = sum(1 for v in venc_list if 0 <= v['DIAS_VENC'] <= 30)
        # Nuevos KPIs
        valor_sstock    = int(sum(it['STOCK_TOTAL'] * it.get('COSTO', 0) for it in items
                                  if it['DIAS_STOCK'] > 45 and it.get('VTA_DIARIA', 0) > 0))
        _dep1_act       = [it for it in activos if it.get('STOCK_DEP1', 0) > 0]
        _dias_dep1_avg  = round(sum(min(999, it['STOCK_DEP1'] / it['VTA_DIARIA']) for it in _dep1_act) / max(1, len(_dep1_act)))
        _dias_gral_avg  = round(sum(min(999, it['DIAS_STOCK']) for it in activos) / max(1, len(activos)))

        abc_dist  = {'A': 0, 'B': 0, 'C': 0}
        stab_dist = {'Estable': 0, 'Variable': 0, 'Errático': 0, 'Inactivo': 0}

        # -- Salud del inventario --
        health = {'q': 0, 'pq': 0, 's': 0, 'a': 0, 'o': 0}
        matrix_abc_salud = {
            'A': {'q': 0, 'pq': 0, 's': 0, 'a': 0, 'o': 0},
            'B': {'q': 0, 'pq': 0, 's': 0, 'a': 0, 'o': 0},
            'C': {'q': 0, 'pq': 0, 's': 0, 'a': 0, 'o': 0},
        }
        matrix_xyz   = {}
        doh_map      = {'Quiebre': 0, '1-10d Crít.': 0, '11-19d Alerta': 0,
                        '20-30d Sano': 0, '31-45d Atención': 0, '+45d Sobrestock': 0}
        aging        = {'f0_30': 0, 'f31_60': 0, 'f61_90': 0, 'f91_180': 0, 'f180': 0}
        cash_flow    = {'w1': 0, 'w2': 0, 'w3': 0, 'w4': 0}
        sub_perf_map = {}

        for it in items:
            abc_dist[it['ABC']] = abc_dist.get(it['ABC'], 0) + 1
            s = it['STABILITY']
            if s in stab_dist:
                stab_dist[s] += 1

            dias    = it['DIAS_STOCK']
            vd      = it['VTA_DIARIA']
            costo   = it['COSTO']
            stk     = it['STOCK_TOTAL']
            capital = round(stk * costo)
            abc     = it['ABC']

            # Estado de salud
            if dias == 0 and vd > 0:    sal = 'q'
            elif 0 < dias <= 10 and vd > 0: sal = 'pq'
            elif 11 <= dias <= 30:      sal = 's'
            elif 31 <= dias <= 45:      sal = 'a'
            else:                       sal = 'o'
            health[sal] += 1
            matrix_abc_salud[abc][sal] += capital

            # ABC/XYZ counts
            key = it['ABC_XYZ']
            matrix_xyz[key] = matrix_xyz.get(key, 0) + 1

            # DOH ranges (valorizado)
            if dias == 0 and vd > 0:        doh_map['Quiebre']           += capital
            elif 1 <= dias <= 10:           doh_map['1-10d Crít.']       += capital
            elif 11 <= dias <= 19:          doh_map['11-19d Alerta']     += capital
            elif 20 <= dias <= 30:          doh_map['20-30d Sano']       += capital
            elif 31 <= dias <= 45:          doh_map['31-45d Atención']   += capital
            else:                           doh_map['+45d Sobrestock']   += capital

            # Aging valorizado
            if   dias <= 30:   aging['f0_30']   += capital
            elif dias <= 60:   aging['f31_60']  += capital
            elif dias <= 90:   aging['f61_90']  += capital
            elif dias <= 180:  aging['f91_180'] += capital
            else:              aging['f180']    += capital

            # Cash flow urgencia compra
            sug = it['SUG_COMPRA']
            if sug > 0 and costo > 0:
                inv = round(sug * costo)
                if dias == 0:        cash_flow['w1'] += inv
                elif dias <= 7:      cash_flow['w2'] += inv
                elif dias <= 14:     cash_flow['w3'] += inv
                else:                cash_flow['w4'] += inv

            # Sub-perfil
            sp = map_nomina.get(it['SKU'], {}).get('sub_perfil', '')
            if sp and sp.lower() not in ('', 'nan'):
                sub_perf_map[sp] = sub_perf_map.get(sp, 0) + capital

        # DOH lista ordenada
        total_doh = sum(doh_map.values()) or 1
        doh_ranges = [
            {'rango': rng, 'stockVal': val, 'pct': round(val / total_doh * 100, 1)}
            for rng, val in doh_map.items()
        ]

        # Sub-perfil top 10
        sub_perfil_pie = sorted(
            [{'name': k, 'value': v} for k, v in sub_perf_map.items()],
            key=lambda x: x['value'], reverse=True
        )[:10]

        # Cargos por analista
        analista_cargo = {}
        for _, r in df_grafana.iterrows():
            sku = str(r.get('SKU', '')).strip().upper()
            analista = str(r.get('Analista', r.get('ANALISTA', ''))).strip() or 'Sin Analista'
            if sku and sku in map_cargos_sku:
                c = map_cargos_sku[sku]
                if analista not in analista_cargo:
                    analista_cargo[analista] = {'skus': set(), 'units': 0, 'debt': 0}
                analista_cargo[analista]['skus'].add(sku)
                analista_cargo[analista]['units'] += c.get('unidades', 0)
                analista_cargo[analista]['debt']  += c.get('monto', 0)
        analistas_cargos = sorted(
            [{'name': k, 'count': len(v['skus']), 'units': v['units'], 'debt': round(v['debt'])}
             for k, v in analista_cargo.items()],
            key=lambda x: x['debt'], reverse=True
        )

        # -- Sub-perfil x cobertura D80 (enriquecido) --
        _sp_d80 = {}
        _total_full = sum(1 for it in items if it.get('ML_VTA30', 0) > 0 or it.get('STOCK_DEP80', 0) > 0)
        for it in items:
            if it.get('ML_VTA30', 0) > 0 or it.get('STOCK_DEP80', 0) > 0:
                sp = it.get('SUB_PERFIL', '') or 'Sin Sub-Perfil'
                if sp not in _sp_d80:
                    _sp_d80[sp] = {'t': 0, 'stk80': 0, 'vtasq60': 0.0, 'dias_sum': 0, 'dias_cnt': 0}
                _sp_d80[sp]['t'] += 1
                stk80 = int(it.get('STOCK_DEP80', 0))
                vta60 = it.get('VTASQ60', 0)
                _sp_d80[sp]['stk80'] += stk80
                _sp_d80[sp]['vtasq60'] += vta60
                vd = vta60 if vta60 > 0 else 0
                if vd > 0 and stk80 > 0:
                    _sp_d80[sp]['dias_sum'] += min(round(stk80 / vd), 999)
                    _sp_d80[sp]['dias_cnt'] += 1
        sub_perfil_d80_kpi = sorted(
            [{'name': sp,
              'total': v['t'],
              'pct': round(v['t'] / _total_full * 100, 1) if _total_full else 0,
              'stk80': v['stk80'],
              'vtasq60': round(v['vtasq60'], 2),
              'dias': round(v['dias_sum'] / v['dias_cnt']) if v['dias_cnt'] else 0,
              'sobrestock': max(0, int(v['stk80'] - v['vtasq60'] * 45)) if v['vtasq60'] > 0 else 0,
             } for sp, v in _sp_d80.items()],
            key=lambda x: x['vtasq60'], reverse=True)
        _all_d80_dias = [round(it['STOCK_DEP80'] / it['VTASQ60'])
                         for it in items
                         if it.get('STOCK_DEP80', 0) > 0 and it.get('VTASQ60', 0) > 0]
        prom_dias_dep80 = round(sum(_all_d80_dias) / len(_all_d80_dias)) if _all_d80_dias else 0

        # -- Matriz Perfil x Sub-Perfil (enriquecida) --
        _pxsp = {}
        for it in items:
            if it['VTA_DIARIA'] > 0:
                pfil = it.get('PERFIL', '') or 'Sin Perfil'
                sp   = it.get('SUB_PERFIL', '') or '—'
                k    = (pfil, sp)
                if k not in _pxsp:
                    _pxsp[k] = {'t': 0, 'sv': 0.0, 'vp': 0.0, 'dias_sum': 0}
                _pxsp[k]['t'] += 1
                _pxsp[k]['sv'] += it['STOCK_TOTAL'] * it['COSTO']
                _pxsp[k]['vp'] += it['VTA_DIARIA'] * 30 * it['COSTO'] if it['STOCK_TOTAL'] == 0 else 0
                _pxsp[k]['dias_sum'] += it['DIAS_STOCK']
        _total_sv_m  = sum(v['sv'] for v in _pxsp.values()) or 1
        _total_act_m = sum(v['t']  for v in _pxsp.values()) or 1
        perfil_matrix_rows = sorted(
            [{'perfil': k[0], 'sub_perfil': k[1],
              'skus': v['t'],
              'dias': min(round(v['dias_sum'] / v['t']), 999) if v['t'] else 0,
              'sv':   round(v['sv']),
              'pct_sv': round(v['sv'] / _total_sv_m * 100, 1),
              'vp':   round(v['vp']),
             } for k, v in _pxsp.items()],
            key=lambda x: x['sv'], reverse=True)
        _vpd_items = [it for it in items if it['VTA_DIARIA'] > 0 and it.get('VPD', 0) > 0]
        _cumpl_vpd = round(sum(min(it['VTASQ60'] / it['VPD'], 2.0) for it in _vpd_items)
                           / len(_vpd_items) * 100, 1) if _vpd_items else 0
        perfil_matrix_kpi = {
            'rows': perfil_matrix_rows,
            'kpis': {
                'dias_prom':  round(sum(v['dias_sum'] for v in _pxsp.values()) / _total_act_m),
                'stock_val':  f"${sum(v['sv'] for v in _pxsp.values()):,.0f}",
                'venta_perd': f"${sum(v['vp'] for v in _pxsp.values()):,.0f}",
                'cumpl_vpd':  f"{_cumpl_vpd}%",
                'combinaciones': len(perfil_matrix_rows),
            },
        }

        kpis = {
            'total_skus':   len(items),
            'activos':      len(activos),
            'quiebres':     len(quiebres),
            'criticos':     len(criticos),
            'valor_inv':    f"${valor_inv:,.0f}",
            'valor_sstock': f"${valor_sstock:,.0f}",
            'total_sug':    sum(it['SUG_COMPRA'] for it in items),
            'sin_stock_ml': len(ml_sin_stock),
            'cumpl_vpd':    f"{_cumpl_vpd}%",
            'dias_dep1':    _dias_dep1_avg,
            'dias_dep80':   prom_dias_dep80,
            'dias_gral':    _dias_gral_avg,
            'total_cargos': f"${tot_cargos:,.0f}",
            'vencidos':     venc_venc,
            'prox_30':      venc_30,
            'abc':              abc_dist,
            'stability':        stab_dist,
            'top_marcas':       [{'marca': m, 'fact': round(f)} for m, f in top_marcas],
            'health':           health,
            'matrix_abc_salud': matrix_abc_salud,
            'matrix_xyz':       matrix_xyz,
            'doh_ranges':       doh_ranges,
            'aging':            aging,
            'cash_flow':        cash_flow,
            'sub_perfil_pie':   sub_perfil_pie,
            'analistas_cargos': analistas_cargos,
            'hist_data':        {it['SKU']: {'desc': it['DESCRIPCION'][:40], 'marca': it['MARCA'],
                                              'prov': it['PROV'], 'hist': hist_map.get(it['SKU'], [])}
                                 for it in sorted([x for x in items if x['VTA_DIARIA'] > 0],
                                                  key=lambda x: x['VTA_DIARIA'], reverse=True)[:200]},
            'sku_data':         {it['SKU']: {
                                    'v60': round(it.get('VTASQ60', it['VTA_DIARIA']), 2),
                                    'v45': round(it.get('VTASQ45', 0), 2),
                                    'v30': round(it.get('VTASQ30', 0), 2),
                                    'v15': round(it.get('VTASQ15', 0), 2),
                                    'vpd': round(it.get('VPD_CPRA', 0), 2),
                                    'vtaia': round(it.get('VTA_IA', 0), 2),
                                    'dep1': int(it.get('STOCK_DEP1', 0)),
                                    'dep80': int(it.get('STOCK_DEP80', 0)),
                                    'mlfull': int(it.get('ML_FULL', 0)),
                                    'dias': it['DIAS_STOCK'],
                                    'smin': round(it.get('STOCK_MIN', 0)),
                                    'smax': round(it.get('STOCK_MAX', 0)),
                                    'mlvta30': int(it.get('ML_VTA30', 0)),
                                    'mlsug': int(it.get('ML_SUG_FULL', 0)),
                                    'disponible': round(it.get('DISPONIBLE', 0)),
                                    'sugcompra': round(it.get('SUG_COMPRA', 0)),
                                    'inversion': round(it.get('INVERSION', 0)),
                                    'perfil': it.get('PERFIL', ''),
                                    'marca': it.get('MARCA', ''),
                                    'prov': it.get('PROV', ''),
                                    'subperfil': it.get('SUB_PERFIL', ''),
                                    'abcxyz': it.get('ABC_XYZ', ''),
                                    'stab': it.get('STABILITY', ''),
                                    'costo': it.get('COSTO', 0),
                                    'lt': int(it.get('LEAD_TIME', 7)),
                                    'agot': it.get('AGOT_EST', ''),
                                    'seg': round(it.get('STOCK_SEG', 0)),
                                    'cargos': it.get('CARGOS_MONTO', 0),
                                    'ventaperdida': it.get('VENTA_PERDIDA', 0),
                                    'ean': it.get('EAN', ''),
                                    'mla': it.get('MLA', ''),
                                    'desc': it.get('DESCRIPCION', '')[:50],
                                    'stock': int(it.get('STOCK_TOTAL', 0)),
                                    'ec': int(it.get('EN_CAMINO', 0)),
                                    'vtad': round(it.get('VTA_DIARIA', 0), 3),
                                    'ss': round(it.get('STOCK_SEG', 0)),
                                    'quiebre': 1 if it.get('QUIEBRE') else 0,
                                 } for it in items},
            'search_index':     [{'sku': it['SKU'], 'desc': it['DESCRIPCION'][:50],
                                   'marca': it['MARCA'], 'prov': it['PROV']}
                                  for it in items if it['VTA_DIARIA'] > 0],
            'sub_perfil_d80':   sub_perfil_d80_kpi,
            'prom_dias_dep80':  prom_dias_dep80,
            'perfil_matrix':    perfil_matrix_kpi,
        }

        # -- Listas finales --
        def _agotar(dias):
            if dias <= 0:  return 'AGOTADO'
            if dias >= 999: return '\u221e'
            try: return (datetime.date.today() + datetime.timedelta(days=int(dias))).strftime('%d/%m/%Y')
            except: return '\u2014'

        # Dep80 VTASQ60 por SKU desde GRAFANA crudo
        dep80_vta60 = {}
        for _, _r80 in df_grafana.iterrows():
            _sku80 = str(_r80.get('SKU', '')).strip().upper()
            if not _sku80 or _sku80 in ('NAN', 'SKU', 'TOTAL'): continue
            _dep80 = str(_r80.get('Deposito', _r80.get('DEPOSITO', ''))).strip()
            if '80' in _dep80:
                dep80_vta60[_sku80] = dep80_vta60.get(_sku80, 0) + sf(_r80.get('VTASQ60', 0))

        inv_list   = sorted(activos, key=lambda x: (0 if x['QUIEBRE'] else 1, x['DIAS_STOCK']))
        _dep80_raw = [it for it in items if it['ML_VTA30'] > 0 or it['STOCK_DEP80'] > 0]
        dep80_list = []
        for _it in sorted(_dep80_raw, key=lambda x: x['ML_VTA30'], reverse=True):
            _vq80  = round(dep80_vta60.get(_it['SKU'], 0), 2)
            _s80   = _it['STOCK_DEP80']
            _d80   = min(round(_s80 / _vq80) if _vq80 > 0 else (999 if _s80 > 0 else 0), 999)
            dep80_list.append(dict(_it, **{
                'VTASQ60_D80': _vq80,
                'DIAS_D80':    round(_d80, 1),
                'AGOT_D80':    _agotar(_d80),
                'DISPONIBLE':  max(0, _it['STOCK_DEP1'] - _it['STOCK_SEG']),
                'ENVIOS_REAL': enviados_sku.get(_it['SKU'], 0),
                'MONTO':       round(_it['ML_SUG_FULL'] * _it['COSTO']),
            }))

        # -- GRAFANA: filas planas por deposito --
        grafana_rows = []
        for _, r in df_grafana.iterrows():
            sku = str(r.get('SKU', '')).strip().upper()
            if not sku or sku in ('NAN', 'SKU', 'TOTAL'):
                continue
            dep   = str(r.get('Deposito', r.get('DEPOSITO', ''))).strip()
            vtar  = sf(r.get('VTASQ60', 0))
            stock = sf(r.get('Stock', r.get('STOCK', 0)))
            vta59 = sf(r.get('VTA60', r.get('TOTAL VENDIDO', 0)))
            costo_g = sf(r.get('Costo', r.get('COSTO', 0)))
            nom   = map_nomina.get(sku, {})
            dias_dep = round(stock / vtar) if vtar > 0 else (999 if stock > 0 else 0)
            grafana_rows.append({
                'SKU':         sku,
                'DESCRIPCION': nom.get('desc') or str(r.get('Descripcion', '')).strip(),
                'MARCA':       nom.get('marca') or str(r.get('Marca', '')).strip(),
                'PROV':        str(r.get('Prov', r.get('PROV', ''))).strip(),
                'DEPOSITO':    dep,
                'VTAR':        round(vtar, 2),
                'STOCK':       round(stock),
                'VTA59':       round(vta59, 2),
                'DIAS_DEP':    min(dias_dep, 999),
                'COSTO':       round(costo_g, 2),
                'ANALISTA':    str(r.get('Analista', r.get('ANALISTA', ''))).strip(),
            })

        # -- OTROS DEPOSITOS (ni dep 1 ni dep 80) --
        _map_lt_sku  = {it['SKU']: it.get('LEAD_TIME', 30) for it in items}
        _map_ec_sku  = {it['SKU']: it.get('EN_CAMINO', 0)  for it in items}
        otros_deps_rows = []
        dep_vistos = {}
        for row in grafana_rows:
            dep = row['DEPOSITO']
            if '80' not in dep and dep not in ('1', '01', ''):
                _vt  = row['VTAR']
                _stk = row['STOCK']
                _sku = row['SKU']
                _lt  = _map_lt_sku.get(_sku, 30)
                _ec  = _map_ec_sku.get(_sku, 0)
                _ss  = math.ceil(2.33 * _vt * math.sqrt(_lt)) if _vt > 0 else 0
                _smin = math.ceil(_vt * _lt + _ss) if _vt > 0 else 0
                _smax = max(math.ceil(_vt * 30), _smin) if _vt > 0 else 0
                _dias = row['DIAS_DEP']
                _status = ('Quiebre'   if _dias == 0 and _vt > 0 else
                           'Crítico'   if 0 < _dias <= 10 else
                           'Saludable' if _dias <= 30 else
                           'Alerta'    if _dias <= 45 else 'Sobrestock')
                _qenv = max(0, _smax - _stk - _ec)
                otros_deps_rows.append({**row,
                    'SS_DEP':        _ss,
                    'STOCK_MIN_DEP': _smin,
                    'STOCK_MAX_DEP': _smax,
                    'ENVIOS_REAL':   enviados_sku.get(_sku, 0),
                    'Q_ENVIAR':      _qenv,
                    'STATUS':        _status,
                })
                dep_vistos[dep] = True

        # -- CONSOLIDADO --
        consolidado_list = sorted(items, key=lambda x: x['VTA_DIARIA'], reverse=True)

        # -- DETALLE MATRIZ (ABC/XYZ con metricas) --
        def _salud_label(it):
            d = it['DIAS_STOCK']; v = it['VTA_DIARIA']
            if d == 0 and v > 0: return 'Quiebre'
            if 0 < d <= 10 and v > 0: return 'Pre-Quiebre'
            if 11 <= d <= 30: return 'Saludable'
            if 31 <= d <= 45: return 'Alerta'
            return 'Sobrestock'

        detalle_matriz = []
        for it in items:
            if it['VTA_DIARIA'] > 0 or it['STOCK_TOTAL'] > 0:
                detalle_matriz.append({
                    'SKU': it['SKU'], 'DESCRIPCION': it['DESCRIPCION'],
                    'MARCA': it['MARCA'], 'PROV': it['PROV'],
                    'ABC': it['ABC'], 'XYZ': it['XYZ'], 'ABC_XYZ': it['ABC_XYZ'],
                    'STABILITY': it['STABILITY'], 'CV': it['CV'],
                    'VTA_DIARIA': it['VTA_DIARIA'], 'VTA_IA': it['VTA_IA'],
                    'VTASQ60': round(it.get('VTASQ60', it['VTA_DIARIA']), 1),
                    'STOCK_TOTAL': it['STOCK_TOTAL'], 'DIAS_STOCK': it['DIAS_STOCK'],
                    'COSTO': it['COSTO'], 'ANOMALY': it['ANOMALY'],
                    'QUIEBRE': it['QUIEBRE'], 'CRITICO': it['CRITICO'],
                    'CAPITAL': round(it['STOCK_TOTAL'] * it['COSTO']),
                    'ESTADO_SALUD': _salud_label(it),
                })
        detalle_matriz.sort(key=lambda x: x['ABC_XYZ'])

        # -- PROVEEDORES --
        prov_map = {}
        prov_items_map = {}  # items con sugerencia de compra por proveedor (para export)
        for it in items:
            p = it['PROV'] or 'Sin Proveedor'
            if p not in prov_map:
                prov_map[p] = {
                    'totalStockVal': 0.0,
                    'totalStockQty': 0.0,
                    'totalVtar': 0.0,
                    'inmoVal': 0.0,
                    'inversion': 0.0,
                }
            pm = prov_map[p]
            pm['totalStockVal'] += it['STOCK_TOTAL'] * it['COSTO']
            pm['totalStockQty'] += it['STOCK_TOTAL']
            pm['totalVtar']     += it['VTA_DIARIA']
            if it['DIAS_STOCK'] > 45:
                pm['inmoVal'] += it['STOCK_TOTAL'] * it['COSTO']
            pm['inversion'] += it['INVERSION']
            if it['SUG_COMPRA'] > 0:
                if p not in prov_items_map:
                    prov_items_map[p] = []
                prov_items_map[p].append({
                    'SKU': it['SKU'], 'Descripcion': it['DESCRIPCION'],
                    'Marca': it['MARCA'], 'Cantidad': it['SUG_COMPRA'],
                    'CostoUnitario': it['COSTO'], 'Total': it['INVERSION'],
                })
        proveedores_list = sorted(
            [{'prov': p,
              'diasStockProm': round(v['totalStockQty'] / v['totalVtar'], 1) if v['totalVtar'] > 0 else 0,
              'totalStockVal': round(v['totalStockVal']),
              'inmoVal':       round(v['inmoVal']),
              'inversion':     round(v['inversion']),
              } for p, v in prov_map.items()],
            key=lambda x: x['totalStockVal'], reverse=True
        )

        # -- PROYECCIONES (30/60/90 dias) --
        proyecciones_list = []
        for it in activos:
            vd = it['VTA_DIARIA']
            ia = it['VTA_IA']
            st = it['STOCK_TOTAL']
            proyecciones_list.append({
                'SKU': it['SKU'], 'DESCRIPCION': it['DESCRIPCION'],
                'MARCA': it['MARCA'], 'VTA_DIARIA': vd, 'VTA_IA': ia,
                'STOCK_TOTAL': st, 'DIAS_STOCK': it['DIAS_STOCK'],
                'PROY_30': round(vd * 30), 'PROY_60': round(vd * 60),
                'PROY_90': round(vd * 90),
                'PROY_IA_30': round(ia * 30) if ia else round(vd * 30),
                'DEFICIT_30': max(0, round(vd * 30) - st),
                'ABC_XYZ': it['ABC_XYZ'], 'COSTO': it['COSTO'],
            })
        proyecciones_list.sort(key=lambda x: x['DEFICIT_30'], reverse=True)

        # -- INMOVILIZADO / SOBRESTOCK (dias > 45, solo con ventas activas) --
        inmovilizado_list = []
        for it in items:
            dias = it['DIAS_STOCK']
            _vd_i = it['VTA_DIARIA']
            # Solo incluir items con ventas activas y stock excedente real
            if dias > 45 and it['STOCK_TOTAL'] > 0 and _vd_i > 0:
                valor = it['STOCK_TOTAL'] * it['COSTO']
                if   dias > 180: ant = '+180d'
                elif dias > 90:  ant = '91-180d'
                elif dias > 60:  ant = '61-90d'
                else:            ant = '46-60d'
                # Fórmula: unidades que exceden 45 días de stock = (dias-45) × venta_diaria
                _unid_exc  = round(_vd_i * (dias - 45))
                _costo_exc = round(_unid_exc * it['COSTO'])
                _pct_exc   = round(_unid_exc / it['STOCK_TOTAL'] * 100, 1) if it['STOCK_TOTAL'] > 0 else 0
                inmovilizado_list.append({
                    'SKU': it['SKU'], 'DESCRIPCION': it['DESCRIPCION'],
                    'MARCA': it['MARCA'], 'PROV': it['PROV'],
                    'STOCK_TOTAL': it['STOCK_TOTAL'], 'DIAS_STOCK': dias,
                    'VTASQ60': round(_vd_i, 2),
                    'VALOR_STOCK': round(valor), 'STOCK_VAL': round(valor),
                    'UNID_EXC':  _unid_exc,
                    'COSTO_EXC': _costo_exc,
                    'PCT_EXC':   _pct_exc,
                    'ANTIGUEDAD': ant,
                    'VTA_DIARIA': _vd_i, 'COSTO': it['COSTO'],
                    'ABC_XYZ': it['ABC_XYZ'],
                })
        inmovilizado_list.sort(key=lambda x: x['DIAS_STOCK'], reverse=True)

        # -- COMBOS (perfil COMBO o SKU empieza con 097) --
        combos_list = []
        for it in items:
            sku = it['SKU']
            perfil = str(it.get('PERFIL', '')).upper()
            if sku.startswith('097') or perfil == 'COMBO':
                _dc = it['DIAS_STOCK']
                _ac = ('+2 años' if _dc > 720 else '18m-2años' if _dc > 540
                       else '1año-18m' if _dc > 360 else '6-12m' if _dc > 180
                       else '4-6m' if _dc > 120 else '2-4m' if _dc > 60
                       else '<2m' if _dc > 0 else 'Sin stock')
                combos_list.append({
                    'SKU': sku, 'DESCRIPCION': it['DESCRIPCION'],
                    'MARCA': it['MARCA'], 'PROV': it['PROV'],
                    'STOCK_DEP1': si(it['STOCK_DEP1']),
                    'STOCK_DEP80': si(it['STOCK_DEP80']),
                    'STOCK_TOTAL': it['STOCK_TOTAL'],
                    'VTA_DIARIA': it['VTA_DIARIA'], 'DIAS_STOCK': _dc,
                    'VTA30':      round(it['VTA_DIARIA'] * 30),
                    'VTASQ60_IA': round(it['VTA_IA'], 2),
                    'EN_CAMINO':  it['EN_CAMINO'],
                    'AGOT_EST':   it['AGOT_EST'],
                    'SUB_PERFIL': it['SUB_PERFIL'],
                    'STOCK_SEG':  it['STOCK_SEG'],
                    'STOCK_MIN':  it['STOCK_MIN'],
                    'STOCK_MAX':  it['STOCK_MAX'],
                    'ANTIGUEDAD': _ac,
                    'QUIEBRE':    it['QUIEBRE'],
                    'CRITICO':    it['CRITICO'],
                    'SUG_COMPRA': it['SUG_COMPRA'],
                    'INVERSION':  it['INVERSION'],
                    'COSTO': it['COSTO'],
                    'ABC_XYZ': it['ABC_XYZ'],
                    'PERFIL': it.get('PERFIL', ''),
                })
        combos_list.sort(key=lambda x: x['VTA_DIARIA'], reverse=True)

        # ── PBI NEGATIVOS ─────────────────────────────────────────────────
        pbi_negativos = []
        if not df_pbi.empty:
            _sc_pbi  = _col(df_pbi, 'SKU')
            _dc_pbi  = _col(df_pbi, 'DESCRIPCION')
            _dep_pbi = [
                ('01', _col(df_pbi, 'DEP 1', 'DEP 01', 'DEP1')),
                ('80', _col(df_pbi, 'DEP 80', 'DEP80')),
                ('81', _col(df_pbi, 'DEP 81', 'DEP81')),
                ('82', _col(df_pbi, 'DEP 82', 'DEP82')),
                ('83', _col(df_pbi, 'DEP 83', 'DEP83')),
                ('87', _col(df_pbi, 'DEP 87', 'DEP87')),
                ('89', _col(df_pbi, 'DEP 89', 'DEP89')),
            ]
            if _sc_pbi:
                for _, _r in df_pbi.iterrows():
                    _sku_p = str(_r.get(_sc_pbi, '')).strip().upper()
                    if not _sku_p or _sku_p in ('NAN', 'SKU', 'TOTAL'):
                        continue
                    _desc_p = str(_r.get(_dc_pbi, '')) if _dc_pbi else ''
                    for _lbl, _col_p in _dep_pbi:
                        if _col_p:
                            _val_p = sf(_r.get(_col_p, 0))
                            if _val_p < 0:
                                pbi_negativos.append({
                                    'sku':   _sku_p,
                                    'desc':  _desc_p,
                                    'punto': _lbl,
                                    'valor': round(_val_p, 2),
                                })
            pbi_negativos.sort(key=lambda x: x['valor'])

        # ── STOCK D1 SIN D80 ──────────────────────────────────────────────
        stock_d1_sin_d80 = []
        for _it_d1 in items:
            _d1_v  = int(_it_d1.get('STOCK_DEP1', 0))
            _d80_v = int(_it_d1.get('STOCK_DEP80', 0))
            if _d1_v > 0 and _d80_v <= 0:
                stock_d1_sin_d80.append({
                    'sku':        _it_d1['SKU'],
                    'desc':       _it_d1['DESCRIPCION'],
                    'marca':      _it_d1['MARCA'],
                    'prov':       _it_d1['PROV'],
                    'dep1':       _d1_v,
                    'dep80':      _d80_v,
                    'vtar_total': round(_it_d1.get('VTASQ60', _it_d1['VTA_DIARIA']), 2),
                    'vtar_d80':   round(dep80_vta60.get(_it_d1['SKU'], 0), 2),
                    'q_enviar':   int(_it_d1.get('ML_SUG_FULL', 0)),
                })
        stock_d1_sin_d80.sort(key=lambda x: x['dep1'], reverse=True)

        # ── SML VS PBI ────────────────────────────────────────────────────
        sml_vs_pbi = []
        _all_svp_skus  = set()
        _map_pbi_d80v  = {}
        if not df_pbi.empty:
            _sc_svp  = _col(df_pbi, 'SKU')
            _d80_svp = _col(df_pbi, 'DEP 80', 'DEP80')
            _dc_svp  = _col(df_pbi, 'DESCRIPCION')
            if _sc_svp:
                for _, _r in df_pbi.iterrows():
                    _sk = str(_r.get(_sc_svp, '')).strip().upper()
                    if not _sk or _sk in ('NAN', 'SKU', 'TOTAL'):
                        continue
                    _all_svp_skus.add(_sk)
                    _map_pbi_d80v[_sk] = {
                        'dep80': sf(_r.get(_d80_svp, 0)) if _d80_svp else 0,
                        'desc':  str(_r.get(_dc_svp, '')) if _dc_svp else '',
                    }
        _map_sml_full2 = {}
        if not df_sml.empty:
            _sc_sf  = _col(df_sml, 'SKU')
            _fc_sf  = _col(df_sml, 'UNIDADES EN FULL')
            if _sc_sf and _fc_sf:
                for _, _r in df_sml.iterrows():
                    _sk = str(_r.get(_sc_sf, '')).strip().upper()
                    if not _sk:
                        continue
                    _all_svp_skus.add(_sk)
                    _map_sml_full2[_sk] = _map_sml_full2.get(_sk, 0) + sf(_r.get(_fc_sf, 0))
        for _sk in _all_svp_skus:
            _pbi_d = _map_pbi_d80v.get(_sk)
            _sml_v = _map_sml_full2.get(_sk)
            if _pbi_d is None and _sml_v is None:
                continue
            _s80_pbi  = round(_pbi_d['dep80']) if _pbi_d else 0
            _s80_meli = round(_sml_v)          if _sml_v is not None else 0
            _diff     = _s80_pbi - _s80_meli
            _nom      = map_nomina.get(_sk, {})
            _costo_u  = map_costo.get(_sk, 0)
            sml_vs_pbi.append({
                'sku':           _sk,
                'desc':          _pbi_d['desc'] if _pbi_d else _nom.get('desc', ''),
                'prov':          _nom.get('prov', ''),
                'sub_perfil':    _nom.get('sub_perfil', ''),
                'stock80_pbi':   _s80_pbi,
                'stock80_meli':  _s80_meli,
                'diferencia':    round(_diff),
                'costo_unitario': round(_costo_u, 2),
                'dif_x_costo':   round(_diff * _costo_u, 2),
                'obs': 'SKU con stock en PBI pero no en MELI' if (_sml_v is None and _s80_pbi > 0) else '',
            })
        sml_vs_pbi.sort(key=lambda x: abs(x['diferencia']), reverse=True)

        # ══════════════════════════════════════════════════════════
        # VTAS SIMPLEX VS MERCADO
        # ══════════════════════════════════════════════════════════
        simplex_mercado = []
        try:
            from datetime import datetime as _dt, timedelta as _td
            _base_xls = _dt(1899, 12, 30)

            def _to_month(v):
                try:
                    iv = int(float(str(v)))
                    if iv > 40000:
                        return (_base_xls + _td(days=iv)).strftime('%Y-%m')
                except Exception:
                    pass
                return str(v)

            def _norm_df(df):
                df = df.copy()
                df.columns = [str(c).strip().upper() for c in df.columns]
                mc = next((c for c in df.columns if 'MES' in c), None)
                brc = next((c for c in df.columns if 'MARCA' in c), None)
                fac = next((c for c in df.columns if 'FACTUR' in c), None)
                uds = next((c for c in df.columns if 'UNIDAD' in c), None)
                if not all([mc, brc, fac, uds]):
                    return _pd.DataFrame()
                df = df[[mc, brc, fac, uds]].copy()
                df.columns = ['MES', 'MARCA', 'FAC', 'UDS']
                df = df[df['MARCA'].notna() & (df['MARCA'] != 0) & (df['MARCA'] != '')].copy()
                df['MES'] = df['MES'].apply(_to_month)
                df['FAC'] = pd.to_numeric(df['FAC'], errors='coerce').fillna(0)
                df['UDS'] = pd.to_numeric(df['UDS'], errors='coerce').fillna(0)
                return df

            if not df_mercado.empty and not df_simplex.empty:
                dm = _norm_df(df_mercado)
                ds = _norm_df(df_simplex)
                if not dm.empty and not ds.empty:
                    # Group by MES+MARCA
                    dm_g = dm.groupby(['MES','MARCA'], as_index=False).agg({'FAC':'sum','UDS':'sum'})
                    dm_g.columns = ['MES','MARCA','MERC_FAC','MERC_UDS']
                    ds_g = ds.groupby(['MES','MARCA'], as_index=False).agg({'FAC':'sum','UDS':'sum'})
                    ds_g.columns = ['MES','MARCA','SIMP_FAC','SIMP_UDS']
                    merged = pd.merge(dm_g, ds_g, on=['MES','MARCA'], how='outer').fillna(0)
                    merged = merged.sort_values(['MES','MARCA'])
                    for _, row in merged.iterrows():
                        mf = float(row['MERC_FAC']); simp_fac = float(row['SIMP_FAC'])
                        mu = float(row['MERC_UDS']); su = float(row['SIMP_UDS'])
                        simplex_mercado.append({
                            'MES':      str(row['MES']),
                            'MARCA':    str(row['MARCA']),
                            'MERC_FAC': round(mf),
                            'MERC_UDS': round(mu),
                            'SIMP_FAC': round(simp_fac),
                            'SIMP_UDS': round(su),
                            'PART_FAC': round(simp_fac/mf*100, 1) if mf > 0 else 0,
                            'PART_UDS': round(su/mu*100, 1) if mu > 0 else 0,
                        })
        except Exception:
            pass

        return {
            'inv':            inv_list[:500],
            'consolidado':    consolidado_list[:800],
            'dep80':          dep80_list[:400],
            'ml_sin_stock':   ml_sin_stock[:300],
            'venc':           sorted([v for v in venc_list if v['DIAS_VENC'] >= 0] +
                                      [v for v in venc_list if v['DIAS_VENC'] < 0][-150:],
                                     key=lambda x: x['DIAS_VENC']),
            'cargos':         cargos_list[:300],
            'enviados':       enviados_list[:400],
            'grafana':        grafana_rows[:600],
            'otros_depositos':otros_deps_rows[:500],
            'detalle_matriz': detalle_matriz[:800],
            'proveedores':    proveedores_list[:200],
            'prov_items':     prov_items_map,
            'proyecciones':   proyecciones_list[:500],
            'inmovilizado':   inmovilizado_list[:500],
            'combos':         combos_list[:200],
            'available_deps': sorted(dep_vistos.keys()),
            'kpis':           kpis,
            'pbi_negativos':   pbi_negativos[:500],
            'stock_d1_sin_d80': stock_d1_sin_d80[:500],
            'sml_vs_pbi':      sml_vs_pbi[:500],
            'simplex_mercado': simplex_mercado[:2000],
            'params':          {'dias_cob': dias_cob, 'base_calc': base_calc},
        }

    except Exception as e:
        import traceback
        return {'error': str(e), 'detalle': traceback.format_exc()}


# ?????? RUTAS ???????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????????
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = request.form.get('user', '').strip().lower()
        pwd  = request.form.get('password', '')
        if USERS.get(user) == pwd:
            session['user'] = user
            return redirect(url_for('index'))
        error = 'Usuario o contrase??a incorrectos'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    data, error = None, None
    if request.method == 'POST':
        file         = request.files.get('file')
        usar_default = request.form.get('usar_default')
        try:
            dias_cob  = max(1, min(365, int(request.form.get('dias_cob', 30))))
        except (ValueError, TypeError):
            dias_cob = 30
        base_calc = request.form.get('base_calc', 'vtasq60')
        if base_calc not in ('vtasq60', 'vpd'):
            base_calc = 'vtasq60'

        if file and file.filename:
            result = procesar_baseapp(file, dias_cob=dias_cob, base_calc=base_calc)
        elif usar_default and os.path.exists(DEFAULT_FILE):
            result = procesar_baseapp(DEFAULT_FILE, dias_cob=dias_cob, base_calc=base_calc)
        else:
            result = {'error': 'No se seleccionó archivo y no se encontró BASEAPP.xlsb.'}

        if 'error' in result:
            error = result['error'] + ('\n\nDetalle:\n' + result.get('detalle', ''))
        else:
            data = result

    now = datetime.date.today().strftime('%d/%m/%Y')
    return render_template('index.html', data=data, error=error, user=session.get('user'), now=now)


@app.route('/export/<section>')
@login_required
def export_excel(section):
    """Descarga en Excel la secci??n solicitada usando datos de sesi??n."""
    return jsonify({'error': 'Sube el archivo primero para exportar.'}), 400


if __name__ == '__main__':
    app.run(debug=True)


