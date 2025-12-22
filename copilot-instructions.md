# Instrucciones para agentes IA — Dashboard Inventario Logística

## Arquitectura

**Stack:** Alpine.js + Tailwind CSS + Chart.js + SheetJS (XLSX)  
**Build:** Vite 5.x | **Tests:** Vitest | **Persistencia:** IndexedDB (db: `InvProV93`, versión 24)

### Estructura de código
```
index.html              → Monolito principal (~5236 líneas) con inventoryApp()
src/
├── data-processor.js   → Transformación Excel (generateSnapshot, buildLookups, classifyABCAndHealth)
├── utils.js            → formatMoney, parseNumber, logger, calculateLinearRegression, detectAnomaly
└── db.js               → IndexedDB: save(), load(), saveSnapshot() - 3 stores (Files, History, DebtHistory)
tests/
└── utils.test.js       → Tests unitarios con Vitest
```

> ⚠️ **CRÍTICO:** La lógica de negocio está en `index.html`, NO en `src/app.js`. El archivo `index.html` contiene `inventoryApp()` con todo el estado reactivo Alpine.js.

## Flujo de datos

```
Excel(.xlsx) → SheetJS → data-processor.js (validación + consolidación por SKU)
            → inventoryApp() en index.html (estado Alpine.js reactivo)
            → db.js (persistencia IndexedDB con snapshots históricos)
```

## Funciones críticas

| Función | Ubicación | Propósito |
|---------|-----------|-----------|
| `calculateRowLogic(item)` | index.html:~3780 | Cálculo compra/stock (UXB, SS, stockMin/Max, seasonalMult, ventaPerdida) |
| `getColumns()` | index.html:~4751 | Define columnas por tab (consolidado, market, matriz_det, dep80, etc.) |
| `generateSnapshot()` | data-processor.js | Genera snapshots de VTAR por SKU para historial |
| `buildLookups()` | data-processor.js | Mapea hojas auxiliares (mapML, mapCargos, mapEnvios, mapPlanML, mapCanasta) |
| `validateSheet()` | data-processor.js | Valida columnas requeridas en hojas Excel |

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

## Comandos

```bash
npm run dev        # http://localhost:8000 (hot-reload, abre navegador auto)
npm run build      # dist/ (producción con sourcemaps, vendor chunks separados)
npm run preview    # Preview del build de producción
npm test           # Vitest watch mode
npm run test:ui    # Interfaz visual de tests
```

## Guía de modificaciones

| Tarea | Archivo | Buscar/Ubicación |
|-------|---------|------------------|
| Agregar columna tabla | index.html | `getColumns()` (~línea 4751) |
| Cambiar cálculo compra/stock | index.html | `calculateRowLogic()` (~línea 3780) |
| Estilos condicionales celda | index.html | `getCellClass(c,r)` (después de getColumns) |
| Nueva hoja Excel | data-processor.js | `buildLookups()` - agregar nuevo bloque |
| Nueva utilidad | src/utils.js | Exportar función + agregar test en tests/utils.test.js |
| Cambiar persistencia | src/db.js | Modificar `save()`/`load()` |
| Nuevo tab UI | index.html | Agregar en `getColumns()` + template HTML |

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
- **Columna no aparece:** revisar que esté en `getColumns()` para el tab correcto
