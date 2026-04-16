/**
 * Utilidades generales del sistema
 * @module utils
 */

/**
 * Formatea un número como moneda argentina
 * @param {number} v - Valor a formatear
 * @returns {string} Valor formateado como "$ 1.234.567"
 */
export function formatMoney(v) {
    return '$ ' + (v || 0).toLocaleString('es-AR', { maximumFractionDigits: 0 });
}

/**
 * Convierte fecha serial de Excel a formato DD/MM/YYYY
 * @param {number} serial - Número serial de Excel
 * @returns {string} Fecha formateada
 */
export function excelDateToJSDate(serial) {
    if (!serial || isNaN(serial)) return serial;
    const utc_days = Math.floor(serial - 25569);
    const utc_value = utc_days * 86400000;
    const date_info = new Date(utc_value);
    const day = String(date_info.getUTCDate()).padStart(2, '0');
    const month = String(date_info.getUTCMonth() + 1).padStart(2, '0');
    const year = date_info.getUTCFullYear();
    return `${day}/${month}/${year}`;
}

/**
 * Calcula regresión lineal para predicción de tendencias
 * @param {number[]} y - Array de valores observados
 * @returns {{slope: number, intercept: number, nextVal: number}} Coeficientes de regresión y predicción
 */
export function calculateLinearRegression(y) {
    const n = y.length;
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    for (let i = 0; i < n; i++) {
        sumX += i;
        sumY += y[i];
        sumXY += i * y[i];
        sumXX += i * i;
    }
    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;
    return { slope, intercept, nextVal: slope * n + intercept };
}

/**
 * Calcula desviación estándar de un array
 * @param {number[]} arr - Array de números
 * @param {number} [mean] - Media (opcional, se calcula si no se provee)
 * @returns {number} Desviación estándar
 */
export function calculateStandardDeviation(arr, mean) {
    if (!arr || arr.length === 0) return 0;
    const n = arr.length;
    const m = mean !== undefined ? mean : arr.reduce((a, b) => a + b, 0) / n;
    return Math.sqrt(arr.map(x => Math.pow(x - m, 2)).reduce((a, b) => a + b, 0) / n);
}

/**
 * Detecta anomalías usando Z-score (> 2.5 desviaciones)
 * @param {number[]} data - Serie temporal de datos
 * @returns {boolean} true si el último valor es anómalo
 */
export function detectAnomaly(data) {
    if (data.length < 5) return false;
    const mean = data.reduce((a, b) => a + b, 0) / data.length;
    const variance = data.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / data.length;
    const stdDev = Math.sqrt(variance);
    if (stdDev === 0) return false;
    const lastVal = data[data.length - 1];
    const zScore = Math.abs((lastVal - mean) / stdDev);
    return zScore > 2.5;
}

/**
 * Limpia y normaliza strings (trim + uppercase)
 * @param {any} s - String a limpiar
 * @returns {string} String normalizado
 */
export function cleanString(s) {
    return String(s || '').trim().toUpperCase();
}

/**
 * Convierte valores a número, manejando formatos de Excel
 * @param {any} v - Valor a convertir
 * @returns {number} Número parseado o 0
 */
/**
 * Parsea números en formato AR/US/EU: 1.234,56 | 1,234.56 | 1234,56 | 1234.56 | 0,117 | 0.117
 * @param {any} v - Valor a convertir
 * @returns {number} Número parseado o 0
 */
export function parseNumber(v) {
    if (typeof v === 'number') return v;
    if (!v) return 0;
    let s = String(v).replace(/[$\s]/g, '');
    // Si tiene ambos separadores
    if (s.match(/^\d{1,3}(\.\d{3})*,\d+$/)) {
        // Formato AR/EU: 1.234,56 => 1234.56
        s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.match(/^\d{1,3}(,\d{3})*\.\d+$/)) {
        // Formato US: 1,234.56 => 1234.56
        s = s.replace(/,/g, '');
    } else if (s.includes(',')) {
        // Solo coma decimal: 0,117 => 0.117
        s = s.replace(',', '.');
    }
    return parseFloat(s) || 0;
}

/**
 * Encuentra índice de columna por múltiples nombres posibles
 * @param {Array} row - Fila de encabezados
 * @param {string[]} keys - Nombres posibles de columna
 * @returns {number} Índice de columna o -1
 */
export function findColumnIndex(row, keys) {
    return row.findIndex(c => 
        keys.some(k => String(c).trim().toUpperCase().includes(k.toUpperCase()))
    );
}

/**
 * Sistema de logging con niveles
 */
export const logger = {
    error: (msg, data) => {
        console.error(`[ERROR] ${new Date().toISOString()} - ${msg}`, data || '');
    },
    warn: (msg) => {
        console.warn(`[WARN] ${new Date().toISOString()} - ${msg}`);
    },
    info: (msg) => {
        console.log(`[INFO] ${new Date().toISOString()} - ${msg}`);
    },
    debug: (msg, data) => {
        if (import.meta.env.DEV) {
            console.log(`[DEBUG] ${msg}`, data || '');
        }
    }
};

/**
 * Cache simple con Map para memoización
 */
export class MemoCache {
    constructor() {
        this.cache = new Map();
    }

    get(key) {
        return this.cache.get(key);
    }

    set(key, value) {
        this.cache.set(key, value);
        return value;
    }

    has(key) {
        return this.cache.has(key);
    }

    clear() {
        this.cache.clear();
    }

    size() {
        return this.cache.size;
    }
}
