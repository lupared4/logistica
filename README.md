# 📊 Dashboard de Inventario Logística

Dashboard interactivo para gestión de inventario construido con **Alpine.js**, **Chart.js** y **SheetJS**.

## ✨ Características

- 📂 Importación de datos desde Excel (.xlsx/.xls)
- 📈 Análisis ABC-XYZ automático
- 🤖 Predicción de demanda con regresión lineal
- 📊 Gráficos interactivos (Chart.js + datalabels)
- 💾 Persistencia local con IndexedDB
- 🎯 Filtros dinámicos y búsqueda
- 📱 Diseño responsive con Tailwind CSS
- ⚡ Cálculo de stock mínimo/máximo
- 🔔 Alertas de quiebre y vencimientos

## 🚀 Instalación

### Requisitos

- **Node.js** >= 18.0
- **npm** >= 9.0

### Pasos

```bash
# 1. Clonar o descargar el repositorio
cd PRUEBA

# 2. Instalar dependencias
npm install

# 3. Iniciar servidor de desarrollo
npm run dev

# 4. Abrir navegador en http://localhost:8000
```

## 📦 Comandos Disponibles

```bash
# Desarrollo (hot-reload)
npm run dev

# Build para producción
npm run build

# Preview de build
npm run preview

# Ejecutar tests
npm test

# Tests con interfaz visual
npm run test:ui
```

## 📁 Estructura del Proyecto

```
PRUEBA/
├── src/
│   ├── app.js              # Aplicación principal Alpine.js
│   ├── utils.js            # Utilidades (formatMoney, logger, etc.)
│   ├── db.js               # Gestión de IndexedDB
│   └── data-processor.js   # Procesamiento de Excel
├── tests/
│   └── utils.test.js       # Tests unitarios
├── index.html              # HTML principal
├── package.json
├── vite.config.js
└── README.md
```

## 📊 Formato de Excel Esperado

El archivo Excel debe contener las siguientes hojas:

### **Hoja "Grafana" (Requerida)**
Columnas mínimas:
- `SKU` - Código del producto
- `Descripcion` - Nombre del producto
- `Stock` - Unidades en stock
- `VTAR` - Venta promedio diaria
- `Deposito` - Código de depósito
- `Marca`, `Proveedor`, `Analista`
- `Costo` - Costo unitario
- `Lead Time` - Días de reposición
- `UXB` - Unidades por bulto

### **Hojas Opcionales**
- `PBI` - Stocks por depósito (DEP 1, DEP 80, etc.)
- `Stock ML` - Estado de publicaciones ML
- `Cargos` - Penalizaciones y cargos
- `Vencimientos` - Fechas de vencimiento de lotes
- `Enviados` - Historial de envíos

## 🔧 Configuración

### Personalizar parámetros

En `index.html`, ajustar parámetros globales:

```javascript
params: {
    diasSuc: 30,      // Días de cobertura sucursales
    diasFull: 30,     // Días de cobertura Full
    diasCompra: 30,   // Días de compra estratégica
    diasOtros: 30     // Días para otros depósitos
}
```

### Cambiar puerto de desarrollo

En `vite.config.js`:

```javascript
server: {
    port: 3000  // Cambiar a puerto deseado
}
```

## 🧪 Testing

Los tests se ejecutan con **Vitest**:

```bash
# Tests en modo watch
npm test

# Tests con cobertura
npm test -- --coverage

# UI visual para tests
npm run test:ui
```

## 🐛 Troubleshooting

### Error: "Faltan columnas requeridas"
✅ Verificar que la hoja "Grafana" contenga al menos: SKU, VTAR, Stock

### La aplicación no guarda datos
✅ Verificar que IndexedDB esté habilitado en el navegador
✅ Abrir DevTools → Application → IndexedDB → Verificar "InvProV93"

### Gráficos no se renderizan
✅ Verificar que estés en la pestaña "Métricas"
✅ Abrir consola (F12) y buscar errores de Chart.js

### Build falla
✅ Ejecutar `npm install` de nuevo
✅ Borrar `node_modules` y `package-lock.json`, reinstalar

## 📝 Changelog

### v2.0.0 (2025-12-12)
- ♻️ Refactorización completa: separación en módulos
- ⚡ Optimización de rendimiento (bucles consolidados)
- 🛡️ Validación robusta de datos de entrada
- 🧪 Tests unitarios con Vitest
- 📦 Migración a Vite (build moderno)
- 💾 Optimización de IndexedDB
- ✨ Memoización de cálculos costosos
- 📖 JSDoc completo para autocomplete

### v1.0.0
- 🎉 Versión inicial

## 📄 Licencia

Uso interno - Logística SA

## 👥 Soporte

Para dudas o problemas, contactar al equipo de desarrollo.

---

**Desarrollado con ❤️ para optimizar la gestión de inventario**
