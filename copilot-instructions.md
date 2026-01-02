# Instrucciones para agentes IA — Dashboard Inventario Logística

## Arquitectura

**Stack:** Alpine.js 3.x + Tailwind CSS + Chart.js 4.x + SheetJS (XLSX)  
**Build:** Vite 5.x | **Tests:** Vitest | **Persistencia:** IndexedDB (db: `InvProV93`, versión 24)

### Estructura de código
```
index.html              → Monolito principal con inventoryApp() en L2139
src/
├── data-processor.js   → Transformación Excel (generateSnapshot, buildLookups, validateSheet)
├── utils.js            → formatMoney, parseNumber, logger, cleanString, findColumnIndex, MemoCache
└── db.js               → IndexedDB: save(), load(), saveSnapshot() - 3 stores (Files, History, DebtHistory)
tests/
└── utils.test.js       → Tests unitarios con Vitest
```

> ⚠️ **CRÍTICO:** La lógica de negocio vive en `index.html` dentro de `inventoryApp()` (línea 2139). NO existe `src/app.js` - todo el estado reactivo Alpine.js está en el HTML principal.

## Flujo de datos

```
Excel(.xlsx) → SheetJS → data-processor.js (validación + consolidación por SKU)
            → inventoryApp() en index.html (estado Alpine.js reactivo)
            → db.js (persistencia IndexedDB con snapshots históricos)
```

## Funciones críticas

| Función | Ubicación | Propósito |
|---------|-----------|-----------|
| `calculateRowLogic(item)` | index.html:L3933 | Cálculo compra/stock (UXB, SS, stockMin/Max, seasonalMult, ventaPerdida) |
| `getColumns()` | index.html:L4934 | Define columnas visibles por tab |
| `generateSnapshot()` | data-processor.js | Genera snapshots de VTAR por SKU para historial |
| `buildLookups()` | data-processor.js | Mapea hojas auxiliares a objetos lookup |
| `validateSheet()` | data-processor.js | Valida columnas requeridas en hojas Excel |

### Utilidades disponibles (src/utils.js)
```javascript
formatMoney(v)              // "$ 1.234.567" (formato AR)
parseNumber(v)              // Maneja "1.234,56" (AR) y "1,234.56" (US)
cleanString(s)              // trim() + toUpperCase()
findColumnIndex(row, keys)  // Busca columna por múltiples aliases
excelDateToJSDate(serial)   // Serial Excel → "DD/MM/YYYY"
calculateLinearRegression(y)// Predicción de tendencia
detectAnomaly(data)         // Z-score > 2.5 = anomalía
logger.info/warn/error/debug// Sistema de logging (nunca console.log directo)
```

## Estado Alpine.js (index.html)

```javascript
masterData      // Array SKUs consolidados (fuente de verdad)
filteredData    // masterData + filtros (marca, proveedor, analista, abc)
paginatedData   // Página actual para renderizado
lookups         // { mapML, mapCargos, mapEnvios, mapPlanML, mapCanasta }
params          // { diasCompra, diasSuc, diasFull }
calcMethod      // 'vtar' (histórico) | 'vpd' (proyectado IA)
currentTab      // 'metricas'|'consolidado'|'market'|'matriz_det'|'proveedores'|'dep80'|'resumen'|...
```

## Tabs disponibles

`market`, `matriz_det`, `consolidado`, `proveedores`, `inmovilizado`, `otros_depositos`, `dep80`, `resumen`, `cargos`, `detalle`, `enviados`, `vencimientos`

## Hojas Excel soportadas

| Hoja | Clave rawData | Columnas clave | Propósito |
|------|---------------|----------------|-----------|
| **Grafana** | `grafana` | SKU, VTAR, Stock, Deposito | **Requerida** - datos principales |
| PBI | `pbi` | SKU, DEP 1, DEP 80, DEP 81... | Stocks por depósito |
| Stock ML | `sml` | SKU, IMPULSAR, ESTADO DE PUBLICACION, Calidad ok | Estado publicaciones ML |
| Plan ML | `pml` | SKU, Recomendación, Unidades sugeridas | Recomendaciones ML |
| Cargos | `cargos` | SKU, Unidades, Cargo por unidad, FECHA, Antigüedad | Penalizaciones (filtra última fecha) |
| Enviados | `enviados` | SKU, ENVIO REALIZADO | Historial envíos |
| Canasta | `canasta` | SKU, FLAG BLOQUEADOS | Bloqueados → 🚩 bandera roja |
| MLA | `mla` | MLA, SKU, DESCRIPCION, ESTADO | Códigos publicación ML (Dep80) |
| STA19 | `sta19` | SKU, EAN, PROV, DESCRIPCION... (+56 cols) | Datos maestros (EAN, UXB, precios) |

## Comandos

```bash
npm run dev        # http://localhost:8000 (hot-reload, abre navegador auto)
npm run build      # dist/ (producción con sourcemaps, vendor chunks separados)
npm run preview    # Preview del build de producción
npm test           # Vitest watch mode
npm run test:ui    # Interfaz visual de tests
```

## Guía de modificaciones

| Tarea | Archivo | Buscar |
|-------|---------|--------|
| Agregar columna tabla | index.html | `getColumns()` (L4934) |
| Cambiar cálculo compra/stock | index.html | `calculateRowLogic()` (L3933) |
| Estilos condicionales celda | index.html | `getCellClass(c,r)` |
| Nueva hoja Excel | data-processor.js | `buildLookups()` |
| Nueva utilidad | src/utils.js | Exportar + test en tests/utils.test.js |
| Cambiar persistencia | src/db.js | `save()`/`load()` |
| Nuevo tab UI | index.html | `getColumns()` + template HTML |

## Convenciones del proyecto

- **JSDoc obligatorio** para funciones exportadas (`@param`, `@returns`, `@throws`)
- **Logging:** `logger.info/warn/error/debug()` de utils.js (nunca `console.log` directo)
- **Imports:** extensión `.js` explícita siempre (ES modules)
- **Columnas Excel:** usar `findColumnIndex(headers, ['NOMBRE', 'ALIAS'])` para tolerancia a variantes
- **Parseo numérico:** siempre `parseNumber()` (maneja formatos AR: `1.234,56` y USD: `1,234.56`)
- **Strings:** limpiar con `cleanString()` → trim + uppercase

## Ejemplo: agregar nueva hoja Excel

```javascript
// En src/data-processor.js → buildLookups()
if (rawData.nuevaHoja?.length) {
    validateSheet(rawData.nuevaHoja[0], ['SKU', 'CAMPO_REQUERIDO']);
    const h = rawData.nuevaHoja[0];
    const iSku = findColumnIndex(h, ['SKU']);
    const iCampo = findColumnIndex(h, ['CAMPO_REQUERIDO', 'ALIAS']);
    
    rawData.nuevaHoja.slice(1).forEach(r => {
        const sku = cleanString(r[iSku]);
        if (sku) lookups.mapNuevo[sku] = parseNumber(r[iCampo]);
    });
}
```

## Ejemplo: agregar nueva columna

```javascript
// En index.html → getColumns() dentro del tab correspondiente
if(this.currentTab==='consolidado') return [
    // ... columnas existentes ...
    {key:'nuevoCampo', label:'NUEVA COLUMNA', editable: false}
];
```

## Lógica de negocio clave (calculateRowLogic)

- **Stock Seguridad (SS):** `2.33 * vtarTotal * sqrt(leadTime)`
- **Stock Mínimo:** `(vtarTotal * leadTime) + SS`
- **Compra por bultos:** siempre redondea hacia arriba con `Math.ceil(necesidad / uxb) * uxb`
- **Días Stock:** `stockGrafana / vtarTotal` (999 si no hay venta)
- **Estados Salud:** Quiebre (≤10d), Por Quebrar (≤17d), Saludable (≤30d), Alerta (≤45d), Sobrestock (>45d)
- **Venta Perdida:** solo si stockRed ≤ 0 Y perfil = 'ACTIVO'

## Troubleshooting

- **Excel no carga:** F12 → Console → buscar errores en `data-processor.js` (validación columnas con `validateSheet`)
- **Datos no actualizan:** verificar que `masterData` se actualice y llamar `calculateRowLogic()` después de cambios
- **Tests fallan:** verificar extensiones `.js` en imports y que Vitest esté corriendo
- **IndexedDB corrupta:** F12 → Application → IndexedDB → eliminar `InvProV93`
- **Columna no aparece:** revisar que esté en `getColumns()` para el tab correcto (L4934+)

## Vendor chunks (Vite)

El build separa automáticamente dependencias en `vendor.js`:
- `alpinejs`, `chart.js`, `xlsx` → manualChunks en [vite.config.js](vite.config.js)

## Patrones importantes

### Iteración sobre hojas Excel
```javascript
// Siempre: slice(1) para saltar headers, cleanString para SKUs
rawData.hoja.slice(1).forEach(r => {
    const sku = cleanString(r[iSku]);
    if (sku && sku !== 'TOTAL') { /* procesar */ }
});
```

### Cálculo con método dual (VTAR vs VPD)
```javascript
// En calculateRowLogic: usar calcMethod para elegir base
const baseVenta = this.calcMethod === 'vpd' && item.vpdCpra > 0 
    ? item.vpdCpra       // Proyectado IA
    : item.vtarTotal;    // Histórico (default)
```

