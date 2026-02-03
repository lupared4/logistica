# Instrucciones para agentes IA — Dashboard Inventario Logística

## Arquitectura

**Stack:** Alpine.js 3.13 + Tailwind CSS (CDN) + Chart.js 4.4 + SheetJS 0.18  
**Build:** Vite 5.0 | **Tests:** Vitest 1.1 | **Persistencia:** IndexedDB (`InvProV93`, v24)

```
index.html              → Monolito (~6173 líneas): inventoryApp() en <script> embebido - TODA la lógica
src/
├── data-processor.js   → Transformación Excel: generateSnapshot(), buildLookups(), validateSheet()
├── utils.js            → formatMoney, parseNumber, logger, cleanString, findColumnIndex, calculateLinearRegression
└── db.js               → IndexedDB: save(), load(), saveSnapshot(), getHistory(), getDebtHistory()
tests/utils.test.js     → Tests Vitest para src/utils.js
vite.config.js          → Server en :8000, chunks: vendor(alpine+chart+xlsx)
```

> ⚠️ **CRÍTICO:** La lógica NO está en `src/app.js` (no existe). Todo el componente Alpine.js `inventoryApp()` vive dentro del `<script>` de `index.html`.

## Flujo de datos

```
Excel(.xlsx/.xlsb) → SheetJS (XLSX.read) → data-processor.js (buildLookups) 
→ inventoryApp() (Alpine.data) → calculateRowLogic() → IndexedDB (db.js)
```

## Funciones clave y ubicaciones exactas

| Función | Archivo | Línea exacta | Propósito |
|---------|---------|--------------|-----------|
| `inventoryApp()` | index.html | L146 (x-data) | Componente Alpine.js raíz |
| `initApp()` | index.html | L2179 | Carga IndexedDB, inicializa tema oscuro/claro |
| `calculateRowLogic(item)` | index.html | L3925 | **CORE:** Cálculo SS, stockMin/Max, UXB, estados salud |
| `getColumns()` | index.html | L5662 | Define columnas visibles por tab (consolidado, dep80, etc.) |
| `getCellClass(col, row)` | index.html | L5778 | Estilos condicionales celda (colores por umbral) |
| `buildLookups(rawData)` | data-processor.js | L56 | Mapea hojas Excel → lookups (ML, Cargos, Envíos, MLA, STA19) |
| `validateSheet(headers, requiredCols)` | data-processor.js | L23 | Valida columnas requeridas (throws Error) |

## Comandos dev

```bash
npm run dev      # http://localhost:8000 (Vite hot-reload)
npm run build    # Producción → dist/ (sourcemaps + manual chunks)
npm run preview  # Preview de build
npm test         # Vitest watch mode
npm run test:ui  # Vitest UI (@vitest/ui)
```

## Convenciones obligatorias

- **JSDoc:** Todas las funciones exportadas requieren `@param`, `@returns` (ver utils.js)
- **Logging:** NUNCA `console.log` → usar `logger.info/warn/error()` de utils.js
- **Imports:** extensión `.js` explícita (`import { x } from './utils.js'`) - ES Modules
- **Columnas Excel:** `findColumnIndex(headers, ['NOMBRE', 'ALIAS'])` para tolerancia (busca por sinónimos)
- **Números:** SIEMPRE `parseNumber(val)` (maneja formato AR `1.234,56` y US `1,234.56`)
- **Strings:** SIEMPRE `cleanString(str)` → trim + uppercase + normalización

## Guía rápida de modificaciones

| Tarea | Ubicación exacta | Ejemplo |
|-------|------------------|---------|
| Agregar columna a tabla | `getColumns()` en index.html (L5662) | `{key:'nuevoCampo', label:'ETIQUETA'}` |
| Cambiar lógica compra/stock | `calculateRowLogic()` en index.html (L3925) | Modificar `necesidadExacta` o `comprarU` |
| Nueva hoja Excel | `buildLookups()` en data-processor.js (L56+) | Agregar `if (rawData.nuevaHoja)` con `findColumnIndex` |
| Nueva utilidad | Exportar en utils.js + test en tests/utils.test.js | Patrón: `export function foo()` + `describe('foo', ...)` |

## Lógica de negocio crítica (calculateRowLogic L3925)

```javascript
// Stock Seguridad: 2.33 * vtarTotal * sqrt(leadTime)  [L3931]
// Stock Mínimo: (vtarTotal * leadTime) + SS           [L3932]
// Stock Máximo: vtarTotal * 30 (mín. stockMin)        [L3933-3934]

// Compra por bultos (L3985-3990):
const uxb = item.uxb || 1;  // Unidades por bulto
cantBultos = Math.ceil(necesidadExacta / uxb);  // SIEMPRE hacia arriba
comprarU = cantBultos * uxb;

// Estados salud (L4010-4016):
// Quiebre(≤10d), Por Quebrar(≤11-17d), Saludable(≤18-30d), Alerta(≤31-45d), Sobrestock(>45d)

// Base cálculo seleccionable (L3969-3972):
const baseVenta = this.calcMethod === 'vpd' && item.vpdCpra > 0 
    ? item.vpdCpra   // VPD_Cpra (proyectado IA)
    : item.vtarTotal; // VTAR (histórico)
```

## Patrón: agregar nueva hoja Excel

```javascript
// 1. En buildLookups() de data-processor.js (~L56+)
if (rawData.nuevaHoja?.length) {
    const h = rawData.nuevaHoja[0];
    const iSku = findColumnIndex(h, ['SKU', 'CODIGO']);  // Tolerancia alias
    const iCampo = findColumnIndex(h, ['MI_CAMPO']);
    
    rawData.nuevaHoja.slice(1).forEach(r => {
        const sku = cleanString(r[iSku]);
        if (sku && sku !== 'TOTAL') {
            lookups.mapNuevoMapa[sku] = parseNumber(r[iCampo]);
        }
    });
}
// 2. Retornar en objeto lookups: { ...lookups, mapNuevoMapa }
// 3. En index.html initApp() (L2179+): agregar a rawData carga desde DB
```

## Troubleshooting

| Problema | Causa | Solución |
|----------|-------|----------|
| Excel no carga | Columnas faltantes | F12 → Ver errores `validateSheet` en consola (data-processor.js L23) |
| Datos no actualizan | `masterData` modificado sin recalc | Llamar `recalculateGlobal()` o `calculateRowLogic(item)` |
| IndexedDB corrupta | Cambio de versión/estructura | F12 → Application → IndexedDB → Eliminar `InvProV93` |
| Tests fallan | Mock de módulos faltante | Verificar imports en tests/utils.test.js (usar paths relativos) |

## Hojas Excel soportadas

| Hoja | Clave rawData | Columnas críticas | Validación |
|------|---------------|-------------------|------------|
| **Grafana** (requerida) | `grafana` | SKU, VTAR, Stock, Deposito, Costo, Lead Time | `validateSheet()` arroja error si falta |
| PBI | `pbi` | SKU, DEP 1, DEP 80, DEP 81-89 | Opcional (deps L56+ data-processor.js) |
| Stock ML | `sml` | SKU, IMPULSAR, ESTADO DE PUBLICACION | Opcional (L73+ data-processor.js) |
| Cargos | `cargos` | SKU, Unidades, Cargo por unidad, FECHA | Opcional (L90+ data-processor.js) |
| SIMPLEX2025 | `simplex` | COD_ARTICU/SKU, MES, Q, VENTA | Opcional (carga en initApp) |
| MLA | `mla` | SKU, MLA (código ML), ESTADO | Opcional (lookups.mapMLA) |
| STA19 | `sta19` | SKU, EAN | Opcional (lookups.mapSTA19) |

## Estado Alpine.js principal (inventoryApp)

```javascript
// index.html x-data="inventoryApp()" (L146)
isAuthenticated    // Login (usuario: Lpared, pass: 1979)
darkMode           // Tema oscuro/claro (localStorage)
masterData         // Array[Object] - fuente de verdad tras calculateRowLogic()
filteredData       // masterData + filtros (search, ABC, estado, etc.)
lookups            // { mapML, mapCargos, mapEnvios, mapPlanML, mapMLA, mapSTA19, mapCanasta }
calcMethod         // 'vtar' (histórico) | 'vpd' (proyectado IA) - switch en L214+ index.html
currentTab         // 'consolidado' | 'dep80' | 'resumen' | 'vencimientos' | etc.
params             // { diasCompra: 30, diasSuc: 7, diasFull: 30 }
rawData            // { grafana, pbi, sml, cargos, vto, ... } - datos crudos Excel
```

## Testing

```javascript
// tests/utils.test.js - Coverage actual
✅ formatMoney(num) → "$ 1.234.567"
✅ excelDateToJSDate(44562) → "01/01/2022"
✅ calculateLinearRegression(data) → { slope, nextVal }
✅ calculateStandardDeviation(data, mean)
✅ detectAnomaly(value, mean, stdDev)
✅ cleanString(str) → uppercase + trim
✅ parseNumber(str) → maneja "1.234,56" y "1,234.56"
✅ findColumnIndex(headers, ['ALIAS1', 'ALIAS2'])

// Agregar tests: import { describe, test, expect } from 'vitest'
```

