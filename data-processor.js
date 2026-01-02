/**
 * Procesamiento y transformación de datos de inventario
 * @module data-processor
 */

import { 
    cleanString, 
    parseNumber, 
    findColumnIndex, 
    excelDateToJSDate,
    calculateLinearRegression,
    calculateStandardDeviation,
    detectAnomaly,
    logger 
} from './utils.js';

/**
 * Valida que la hoja de Excel tenga las columnas requeridas
 * @param {Array} headers - Fila de encabezados
 * @param {string[]} requiredCols - Columnas requeridas
 * @throws {Error} Si faltan columnas críticas
 */
function validateSheet(headers, requiredCols) {
    const missingCols = requiredCols.filter(col => 
        !headers.some(h => String(h).toUpperCase().includes(col.toUpperCase()))
    );
    
    if (missingCols.length > 0) {
        throw new Error(`❌ Faltan columnas requeridas: ${missingCols.join(', ')}`);
    }
}

/**
 * Genera snapshot de datos para historial
 * @param {Array} rawGrafana - Datos crudos de Grafana
 * @returns {Object} Snapshot con SKU y VTAR
 */
export function generateSnapshot(rawGrafana) {
    try {
        const hG = rawGrafana[0];
        const iSku = findColumnIndex(hG, ['SKU']);
        const iVtar = findColumnIndex(hG, ['VTAR']);
        
        const snap = {};
        rawGrafana.slice(1).forEach(r => {
            const s = cleanString(r[iSku]);
            if (s && s !== 'TOTAL') {
                const v = parseNumber(r[iVtar]);
                if (!snap[s]) snap[s] = { v: 0 };
                snap[s].v += v;
            }
        });
        return snap;
    } catch (e) {
        logger.error('Error generando snapshot', e);
        return {};
    }
}

/**
 * Construye lookups desde hojas auxiliares (ML, Cargos, Envíos)
 * @param {Object} rawData - Datos crudos de todas las hojas
 * @returns {Object} Objeto con mapML, mapCargos, mapEnvios, mapPlanML
 */
export function buildLookups(rawData) {
    const lookups = {
        mapML: {},
        mapCargos: {},
        mapEnvios: {},
        mapPlanML: {},
        mapCanasta: {},
        mapMLA: {}
    };

    // ML Stock
    if (rawData.sml && rawData.sml.length) {
        const h = rawData.sml[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iI = findColumnIndex(h, ['IMPULSAR']);
        const iEstado = findColumnIndex(h, ['ESTADO DE PUBLICACION']);
        const iCalidad = findColumnIndex(h, ['Calidad ok']);

        rawData.sml.slice(1).forEach(r => {
            const s = cleanString(r[iS]);
            if (s) {
                lookups.mapML[s] = {
                    impulsar: String(r[iI]).includes('SI'),
                    estado: r[iEstado],
                    calidad: r[iCalidad]
                };
            }
        });
    }

    // Cargos (solo última fecha)
    if (rawData.cargos && rawData.cargos.length) {
        const h = rawData.cargos[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iU = findColumnIndex(h, ['Unidades']);
        const iUCost = findColumnIndex(h, ['Cargo por unidad']);
        const iDate = findColumnIndex(h, ['FECHA']);
        const iAnt = findColumnIndex(h, ['Antigüedad']);

        let latestDate = 0;
        if (iDate > -1) {
            rawData.cargos.slice(1).forEach(r => {
                const d = r[iDate];
                if (typeof d === 'number' && d > latestDate) latestDate = d;
            });
        }

        rawData.cargos.slice(1).forEach(r => {
            const rowDate = r[iDate];
            if (iDate === -1 || rowDate === latestDate) {
                const s = cleanString(r[iS]);
                if (s) {
                    if (!lookups.mapCargos[s]) {
                        lookups.mapCargos[s] = { monto: 0, unidades: 0, antiguedad: '' };
                    }
                    const u = parseNumber(r[iU]);
                    const uc = parseNumber(r[iUCost]);
                    lookups.mapCargos[s].unidades += u;
                    lookups.mapCargos[s].monto += (u * uc);
                    if (r[iAnt]) lookups.mapCargos[s].antiguedad = r[iAnt];
                }
            }
        });
    }

    // Plan ML
    if (rawData.pml && rawData.pml.length) {
        const h = rawData.pml[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iRec = findColumnIndex(h, ['Recomendación']);
        const iSug = findColumnIndex(h, ['Unidades sugeridas', 'sugeridas']);

        rawData.pml.slice(1).forEach(r => {
            const s = cleanString(r[iS]);
            if (s) {
                const recText = String(r[iRec] || '');
                lookups.mapPlanML[s] = {
                    rec: recText,
                    sug: parseNumber(r[iSug]),
                    esUrgente: recText.toLowerCase().includes('urgencia') || 
                               recText.toLowerCase().includes('perdiendo')
                };
            }
        });
    }

    // Envíos históricos
    if (rawData.enviados && rawData.enviados.length) {
        const h = rawData.enviados[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iCant = findColumnIndex(h, ['ENVIO REALIZADO']);

        rawData.enviados.slice(1).forEach(r => {
            const s = cleanString(r[iS]);
            if (s) {
                lookups.mapEnvios[s] = (lookups.mapEnvios[s] || 0) + parseNumber(r[iCant]);
            }
        });
    }

    // Canasta (FLAG BLOQUEADOS)
    if (rawData.canasta && rawData.canasta.length) {
        const h = rawData.canasta[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iFlag = findColumnIndex(h, ['FLAG BLOQUEADOS', 'BLOQUEADOS', 'BLOQUEADO']);

        rawData.canasta.slice(1).forEach(r => {
            const s = cleanString(r[iS]);
            if (s) {
                const flagVal = String(r[iFlag] || '').toUpperCase().trim();
                lookups.mapCanasta[s] = {
                    bloqueado: flagVal === 'SI' || flagVal === 'SÍ' || flagVal === 'S'
                };
            }
        });
    }

    // MLA (Códigos de publicación Mercado Libre - Depósito 80)
    if (rawData.mla && rawData.mla.length) {
        const h = rawData.mla[0];
        const iS = findColumnIndex(h, ['SKU']);
        const iMLA = findColumnIndex(h, ['MLA']);
        const iEstado = findColumnIndex(h, ['ESTADO']);

        rawData.mla.slice(1).forEach(r => {
            const s = cleanString(r[iS]);
            if (s) {
                lookups.mapMLA[s] = {
                    mla: cleanString(r[iMLA]),
                    estado: cleanString(r[iEstado])
                };
            }
        });
    }

    return lookups;
}

/**
 * Procesa datos de Grafana consolidando información por SKU
 * OPTIMIZADO: Un solo bucle para múltiples cálculos
 * @param {Array} rawGrafana - Datos crudos de Grafana
 * @returns {Object} Datos consolidados por SKU
 */
export function processGrafanaData(rawGrafana) {
    if (!rawGrafana || rawGrafana.length < 2) {
        throw new Error('❌ La hoja Grafana está vacía o no tiene datos');
    }

    const hG = rawGrafana[0];
    
    // Validar columnas requeridas
    validateSheet(hG, ['SKU', 'VTAR', 'Stock']);

    // Índices de columnas
    const indices = {
        sku: findColumnIndex(hG, ['SKU']),
        dep: findColumnIndex(hG, ['Deposito']),
        vtar: findColumnIndex(hG, ['VTAR']),
        vpd: findColumnIndex(hG, ['VPD_Cpra']),
        desc: findColumnIndex(hG, ['Descripcion']),
        marca: findColumnIndex(hG, ['Marca']),
        prov: findColumnIndex(hG, ['Proveedor', 'Prov']),
        analista: findColumnIndex(hG, ['Analista']),
        costo: findColumnIndex(hG, ['Costo', 'Reposición']),
        lt: findColumnIndex(hG, ['Lead']),
        stock: findColumnIndex(hG, ['Stock']),
        uxb: findColumnIndex(hG, ['UXB']),
        camino: findColumnIndex(hG, ['COMPRAS']),
        vta59: findColumnIndex(hG, ['TOTAL VENDIDO', '59 DÍAS', 'VENDIDO 59']),
        perfil: findColumnIndex(hG, ['Perfil'])
    };

    // Detectar columnas históricas (-1, -2, ..., -60)
    const histIndices = [];
    for (let i = 1; i <= 60; i++) {
        const ix = findColumnIndex(hG, [`-${i}`]);
        if (ix > -1) histIndices.push({ idx: ix, day: i });
    }

    const data = {};
    const flatRows = [];

    // PROCESAMIENTO OPTIMIZADO: Un solo bucle
    rawGrafana.slice(1).forEach(r => {
        const sku = cleanString(r[indices.sku]);
        if (!sku || sku === 'TOTAL') return;

        const dep = cleanString(r[indices.dep]);
        const v = parseNumber(r[indices.vtar]);
        const st = parseNumber(r[indices.stock]);
        const vta59 = parseNumber(r[indices.vta59]);

        // Inicializar SKU si no existe
        if (!data[sku]) {
            data[sku] = {
                sku,
                desc: r[indices.desc] || '-',
                marca: r[indices.marca] || '-',
                prov: r[indices.prov] || '-',
                analista: r[indices.analista] || '-',
                costo: parseNumber(r[indices.costo]),
                lt: parseNumber(r[indices.lt]) || 30,
                vpdCpra: parseNumber(r[indices.vpd]),
                uxb: parseNumber(r[indices.uxb]) || 1,
                perfil: (indices.perfil > -1 ? r[indices.perfil] : '') || 'Sin Clasificar',
                vtarTotal: 0,
                vtar80: 0,
                vtar1: 0,
                vtarSuc: 0,
                stockGrafana: 0,
                comprasEnCamino: 0,
                vta59Total: 0,
                histDaily: [],
                vtarBreakdown: {},
                seasonalMult: 1
            };
        }

        // Acumular datos históricos (solo una vez por SKU)
        if (histIndices.length > 0 && data[sku].histDaily.length === 0) {
            const dailySales = histIndices.map(item => parseNumber(r[item.idx]));
            data[sku].histDaily = dailySales;

            // Calcular promedios por períodos
            const calcAvg = (days) => {
                const slice = dailySales.slice(0, days);
                const sum = slice.reduce((a, b) => a + b, 0);
                return days > 0 && slice.length > 0 ? sum / days : 0;
            };

            data[sku].vtar15 = calcAvg(15);
            data[sku].vtar30 = calcAvg(30);
            data[sku].vtar45 = calcAvg(45);
            data[sku].vtar60 = calcAvg(60);
        }

        // Breakdown por depósito
        const depNum = dep.match(/\d+/)?.[0] || '';
        if (depNum && ['82', '86', '87', '89'].includes(depNum)) {
            if (!data[sku].vtarBreakdown[depNum]) data[sku].vtarBreakdown[depNum] = 0;
            data[sku].vtarBreakdown[depNum] += v;
        }

        // Acumuladores
        data[sku].vtarTotal += v;
        data[sku].stockGrafana += st;
        data[sku].vta59Total += vta59;
        if (indices.camino > -1) data[sku].comprasEnCamino += parseNumber(r[indices.camino]);

        // Clasificación por depósito
        if (dep.includes('80') || dep.includes('FULL')) {
            data[sku].vtar80 += v;
        } else if (dep.includes('1') || dep.includes('CENTRAL')) {
            data[sku].vtar1 += v;
        } else {
            data[sku].vtarSuc += v;
        }

        // Fila plana para vista "Detalle"
        flatRows.push({
            id: Math.random().toString(36).substr(2, 9),
            sku,
            desc: r[indices.desc] || data[sku]?.desc || '-',
            marca: r[indices.marca] || '-',
            prov: r[indices.prov] || '-',
            dep,
            vtar: v,
            stock: st,
            vta59,
            diasStockDep: v > 0 ? st / v : (st > 0 ? 999 : 0),
            costo: parseNumber(r[indices.costo]),
            analista: r[indices.analista] || '-'
        });
    });

    return { data, flatRows };
}

/**
 * Enriquece datos con análisis predictivo (IA, anomalías, estabilidad)
 * @param {Object} item - Objeto de datos del SKU
 * @returns {Object} Item enriquecido
 */
export function enrichWithAnalytics(item) {
    if (item.histDaily && item.histDaily.length > 5) {
        const chrono = [...item.histDaily].reverse();
        const reg = calculateLinearRegression(chrono);
        item.vtarIa = Math.max(0, reg.nextVal);
        item.isAnomaly = detectAnomaly(chrono);
    } else {
        item.vtarIa = 0;
        item.isAnomaly = false;
    }

    // Análisis de estabilidad (Coeficiente de Variación)
    if (item.histDaily.length > 0) {
        item.stdDev = calculateStandardDeviation(item.histDaily, item.vtarTotal);
        item.cv = item.vtarTotal > 0 ? item.stdDev / item.vtarTotal : 0;

        if (item.vtarTotal === 0) {
            item.stability = 'Inactivo';
        } else if (item.cv < 0.3) {
            item.stability = 'Estable';
        } else if (item.cv < 0.7) {
            item.stability = 'Variable';
        } else {
            item.stability = 'Errático';
        }
    } else {
        item.stability = 'S/D';
        item.cv = 0;
    }

    return item;
}

/**
 * Clasifica items en categorías ABC basado en valor de venta
 * OPTIMIZADO: Un solo bucle para ABC + Matriz de Salud
 * @param {Array} items - Array de items procesados
 * @returns {Object} Items con clasificación ABC y estadísticas de matriz
 */
export function classifyABCAndHealth(items) {
    const totVenta = items.reduce((s, i) => s + (i.vtarTotal * i.costo), 0);
    
    // Ordenar por valor de venta (descendente)
    items.sort((a, b) => (b.vtarTotal * b.costo) - (a.vtarTotal * a.costo));

    let acc = 0;
    const matrix = {
        A: { q: 0, pq: 0, s: 0, a: 0, o: 0 },
        B: { q: 0, pq: 0, s: 0, a: 0, o: 0 },
        C: { q: 0, pq: 0, s: 0, a: 0, o: 0 }
    };
    const matrixCounts = {};

    // BUCLE OPTIMIZADO: ABC + XYZ + Matriz de Salud en una sola pasada
    items.forEach(p => {
        // ABC
        acc += p.vtarTotal * p.costo;
        const pct = totVenta ? acc / totVenta : 0;
        p.abc = pct <= 0.8 ? 'A' : (pct <= 0.95 ? 'B' : 'C');

        // XYZ (Estabilidad)
        let xyz = 'Z';
        if (p.stability === 'Estable') xyz = 'X';
        else if (p.stability === 'Variable') xyz = 'Y';
        p.abc_xyz = p.abc + xyz;
        matrixCounts[p.abc_xyz] = (matrixCounts[p.abc_xyz] || 0) + 1;

        // Salud (días de stock)
        let status = '';
        if (p.diasStock <= 10) status = 'q';
        else if (p.diasStock <= 17) status = 'pq';
        else if (p.diasStock <= 30) status = 's';
        else if (p.diasStock <= 45) status = 'a';
        else status = 'o';

        matrix[p.abc][status] += p.stockGrafana * p.costo;
    });

    return { matrix, matrixCounts };
}


