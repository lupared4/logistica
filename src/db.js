/**
 * Gestión de IndexedDB con optimizaciones
 * @module db
 */

import { logger } from './utils.js';

const DB_CONFIG = {
    name: 'InvProV93',
    version: 24,
    stores: {
        files: 'Files',
        history: 'History',
        debtHistory: 'DebtHistory'
    }
};

/**
 * Abre o crea la base de datos IndexedDB
 * @returns {Promise<IDBDatabase>}
 */
async function getDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_CONFIG.name, DB_CONFIG.version);
        
        request.onupgradeneeded = (e) => {
            const db = e.target.result;
            
            if (!db.objectStoreNames.contains(DB_CONFIG.stores.files)) {
                db.createObjectStore(DB_CONFIG.stores.files);
            }
            
            if (!db.objectStoreNames.contains(DB_CONFIG.stores.history)) {
                db.createObjectStore(DB_CONFIG.stores.history, { 
                    keyPath: 'id', 
                    autoIncrement: true 
                });
            }
            
            if (!db.objectStoreNames.contains(DB_CONFIG.stores.debtHistory)) {
                db.createObjectStore(DB_CONFIG.stores.debtHistory, { 
                    keyPath: 'date' 
                });
            }
        };
        
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

/**
 * Guarda datos en IndexedDB
 * @param {string} key - Clave de almacenamiento
 * @param {any} data - Datos a guardar
 */
export async function save(key, data) {
    try {
        const db = await getDB();
        return new Promise((resolve) => {
            const tx = db.transaction(DB_CONFIG.stores.files, 'readwrite');
            tx.objectStore(DB_CONFIG.stores.files).put(data, key);
            tx.oncomplete = () => {
                logger.debug(`Guardado: ${key}`);
                resolve();
            };
        });
    } catch (e) {
        logger.error('Error al guardar en DB', { key, error: e.message });
    }
}

/**
 * Carga datos desde IndexedDB
 * @param {string} key - Clave de almacenamiento
 * @returns {Promise<any>} Datos recuperados o null
 */
export async function load(key) {
    try {
        const db = await getDB();
        return new Promise((resolve) => {
            const tx = db.transaction(DB_CONFIG.stores.files, 'readonly');
            const request = tx.objectStore(DB_CONFIG.stores.files).get(key);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve(null);
        });
    } catch (e) {
        logger.error('Error al cargar de DB', { key, error: e.message });
        return null;
    }
}

/**
 * Guarda snapshot histórico de datos
 * @param {Object} data - Snapshot de datos
 */
export async function saveSnapshot(data) {
    try {
        const db = await getDB();
        const tx = db.transaction(DB_CONFIG.stores.history, 'readwrite');
        const store = tx.objectStore(DB_CONFIG.stores.history);
        const today = new Date().toISOString().slice(0, 10);
        store.add({ date: today, data: data });
        logger.info(`Snapshot guardado: ${today}`);
    } catch (e) {
        logger.warn('No se pudo guardar snapshot', e.message);
    }
}

/**
 * Guarda historial de deuda
 * @param {number} totalDebt - Monto total de deuda
 */
export async function saveDebtHistory(totalDebt) {
    try {
        const db = await getDB();
        const tx = db.transaction(DB_CONFIG.stores.debtHistory, 'readwrite');
        const store = tx.objectStore(DB_CONFIG.stores.debtHistory);
        const today = new Date().toISOString().slice(0, 10);
        store.put({ date: today, val: totalDebt });
    } catch (e) {
        logger.warn('No se pudo guardar historial de deuda');
    }
}

/**
 * Obtiene historial completo
 * @returns {Promise<Array>}
 */
export async function getHistory() {
    try {
        const db = await getDB();
        return new Promise((resolve) => {
            const tx = db.transaction(DB_CONFIG.stores.history, 'readonly');
            const request = tx.objectStore(DB_CONFIG.stores.history).getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve([]);
        });
    } catch (e) {
        return [];
    }
}

/**
 * Obtiene historial de deuda
 * @returns {Promise<Array>}
 */
export async function getDebtHistory() {
    try {
        const db = await getDB();
        return new Promise((resolve) => {
            const tx = db.transaction(DB_CONFIG.stores.debtHistory, 'readonly');
            const request = tx.objectStore(DB_CONFIG.stores.debtHistory).getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => resolve([]);
        });
    } catch (e) {
        return [];
    }
}

/**
 * Limpia toda la base de datos
 * @returns {Promise<void>}
 */
export async function clear() {
    return new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(DB_CONFIG.name);
        request.onsuccess = () => {
            logger.info('Base de datos limpiada');
            resolve();
        };
    });
}

export const DB = {
    save,
    load,
    saveSnapshot,
    saveDebtHistory,
    getHistory,
    getDebtHistory,
    clear
};
