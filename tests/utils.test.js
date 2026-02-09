/**
 * Tests unitarios para funciones de utilidad
 */

import { describe, test, expect } from 'vitest';
import {
    formatMoney,
    excelDateToJSDate,
    calculateLinearRegression,
    calculateStandardDeviation,
    detectAnomaly,
    cleanString,
    parseNumber,
    findColumnIndex
} from '../src/utils.js';

describe('Formateo de moneda', () => {
    test('formatea números correctamente', () => {
        expect(formatMoney(1234567)).toBe('$ 1.234.567');
        expect(formatMoney(0)).toBe('$ 0');
        expect(formatMoney(null)).toBe('$ 0');
    });

    test('redondea decimales', () => {
        expect(formatMoney(1234.56)).toBe('$ 1.235');
        expect(formatMoney(1234.49)).toBe('$ 1.234');
    });
});

describe('Conversión de fechas Excel', () => {
    test('convierte seriales de Excel correctamente', () => {
        // 44562 = 01/01/2022 en Excel
        expect(excelDateToJSDate(44562)).toBe('01/01/2022');
    });

    test('maneja valores inválidos', () => {
        expect(excelDateToJSDate(null)).toBe(null);
        expect(excelDateToJSDate('texto')).toBe('texto');
        expect(excelDateToJSDate(NaN)).toBe(NaN);
    });
});

describe('Regresión lineal', () => {
    test('calcula pendiente e intersección correctamente', () => {
        const data = [1, 2, 3, 4, 5];
        const result = calculateLinearRegression(data);
        
        expect(result.slope).toBeCloseTo(1.0, 1);
        expect(result.nextVal).toBeCloseTo(6.0, 1);
    });

    test('predice siguiente valor', () => {
        const data = [10, 20, 30, 40];
        const result = calculateLinearRegression(data);
        
        expect(result.nextVal).toBeCloseTo(50, 0);
    });

    test('maneja series constantes', () => {
        const data = [5, 5, 5, 5];
        const result = calculateLinearRegression(data);
        
        expect(result.slope).toBeCloseTo(0, 1);
        expect(result.nextVal).toBeCloseTo(5, 1);
    });
});

describe('Desviación estándar', () => {
    test('calcula desviación correctamente', () => {
        const data = [2, 4, 4, 4, 5, 5, 7, 9];
        const mean = 5;
        const result = calculateStandardDeviation(data, mean);
        
        expect(result).toBeCloseTo(2.0, 1);
    });

    test('devuelve 0 para array vacío', () => {
        expect(calculateStandardDeviation([])).toBe(0);
        expect(calculateStandardDeviation(null)).toBe(0);
    });

    test('calcula media automáticamente si no se provee', () => {
        const data = [1, 2, 3, 4, 5];
        const result = calculateStandardDeviation(data);
        
        expect(result).toBeGreaterThan(0);
    });
});

describe('Detección de anomalías', () => {
    test('detecta valores anómalos', () => {
        const data = [10, 12, 11, 13, 10, 100]; // 100 es anómalo
        expect(detectAnomaly(data)).toBe(true);
    });

    test('no detecta anomalías en datos normales', () => {
        const data = [10, 12, 11, 13, 10, 12];
        expect(detectAnomaly(data)).toBe(false);
    });

    test('maneja arrays pequeños sin error', () => {
        const data = [1, 2];
        expect(detectAnomaly(data)).toBe(false);
    });

    test('maneja series constantes', () => {
        const data = [5, 5, 5, 5, 5];
        expect(detectAnomaly(data)).toBe(false);
    });
});

describe('Limpieza de strings', () => {
    test('normaliza strings correctamente', () => {
        expect(cleanString('  hola  ')).toBe('HOLA');
        expect(cleanString('MiXeD')).toBe('MIXED');
    });

    test('maneja valores null/undefined', () => {
        expect(cleanString(null)).toBe('');
        expect(cleanString(undefined)).toBe('');
    });

    test('convierte números a string', () => {
        expect(cleanString(123)).toBe('123');
    });
});

describe('Parseo de números', () => {
    test('parsea números con formato', () => {
        expect(parseNumber('$1,234.56')).toBeCloseTo(1234.56, 2);
        expect(parseNumber('1.234,56')).toBeCloseTo(1234.56, 2);
        expect(parseNumber('1,234')).toBeCloseTo(1234, 2);
    });

    test('maneja valores ya numéricos', () => {
        expect(parseNumber(123.45)).toBe(123.45);
    });

    test('devuelve 0 para valores inválidos', () => {
        expect(parseNumber(null)).toBe(0);
        expect(parseNumber('')).toBe(0);
        expect(parseNumber('abc')).toBe(0);
    });
});

describe('Búsqueda de columnas', () => {
    test('encuentra columna por múltiples nombres', () => {
        const headers = ['ID', 'Nombre', 'Stock Total', 'Precio'];
        
        expect(findColumnIndex(headers, ['STOCK', 'Stock'])).toBe(2);
        expect(findColumnIndex(headers, ['precio', 'cost'])).toBe(3);
    });

    test('devuelve -1 si no encuentra', () => {
        const headers = ['ID', 'Nombre'];
        
        expect(findColumnIndex(headers, ['inexistente'])).toBe(-1);
    });

    test('es case-insensitive', () => {
        const headers = ['SKU', 'DESCRIPCION'];
        
        expect(findColumnIndex(headers, ['sku'])).toBe(0);
        expect(findColumnIndex(headers, ['descripcion'])).toBe(1);
    });
});

describe('Casos edge de cálculos', () => {
    test('regresión con 1 solo punto', () => {
        const result = calculateLinearRegression([5]);
        expect(result.nextVal).toBeDefined();
    });

    test('anomalía en serie corta', () => {
        expect(detectAnomaly([1, 2])).toBe(false);
    });

    test('formatMoney con números muy grandes', () => {
        const result = formatMoney(999999999);
        expect(result).toContain('999');
    });
});
