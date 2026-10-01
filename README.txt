DESIERTO FLORIDO · PWA V0.6 (identificación asistida en terreno + reconocimiento de fotos + floración)

USO
1. En esta carpeta ejecutar: python -m http.server 8000  y abrir http://localhost:8000
2. Para GPS/cámara en el teléfono e instalación PWA, servir por HTTPS (hosting estático). localhost también es contexto seguro.
3. Visitar una vez online: el service worker guarda interfaz, catálogo y mapa para uso sin señal.
   iOS: Compartir > Añadir a pantalla de inicio. Android: menú > Instalar aplicación.
4. Tras cambiar archivos, recargar con Ctrl+Shift+R (el service worker puede servir la versión anterior una vez).

IDENTIFICAR (pestaña ⌕)
Foto → tocar un pétalo (estima el color) → GPS y fecha → preguntas → ranking de especies con % → "Es esta → registrar".
Puntaje aproximadamente bayesiano: P(S | M,G,T,I) ∝ P(M|S)·P(G|S)·P(T|S)·P(I|S)·P(S)
  M = respuestas (color, tipo de flor, porte, hábito, geófita, carnosa, espinas, costa/interior, ciclo)
  G = latitud GPS vs. rango latitudinal derivado de las regiones de la ficha
  T = mes de la fecha vs. perfil mensual de floración (107 especies). Desactivable con "La planta está en flor".
      Datos: iNaturalist, regiones de Atacama + Coquimbo (Chile si hay pocos), observaciones anotadas "en flor"
      (58 especies) o, si faltan, todas las observaciones (47; dato más débil, pesa menos). Conteos divididos por el
      total de observaciones de plantas de cada mes (corrige que sep-oct concentren ~8× más visitas) y suavizados
      hacia "sin información" cuando la muestra es pequeña. Nunca descarta: solo reordena.
  I = reconocimiento de fotos en el dispositivo (vision.js + model/): DINOv2-small + clasificador lineal, 107 especies,
      91% top-1 / 97% top-3 en validación cruzada. Descarga única ~40 MB (modelo 25 MB + motor ONNX 14 MB), luego sin señal.
      Varias fotos de la misma planta se combinan. Especies sin fotos de entrenamiento reciben valor neutro.
      Reentrenar: ver ../model_training/README.txt.
- Un dato ausente nunca descarta una especie. Un dato contradictorio penaliza según su procedencia:
  libro (fuerte) > nombre común > por_verificar (débil).
- La pregunta "sugerida" es la de mayor ganancia de información, ponderada por lo fácil que es responderla.
- "¿Qué observar para confirmar?" lista los rasgos conocidos que separan a la primera candidata de las siguientes.

DATOS
- catalogo.sqlite: fuente de verdad. species.json se genera con:  python tools/build_catalog.py
- data/floracion_inat.csv: conteos mensuales y perfil de floración. Actualizar con  python tools/fetch_phenology.py
  (≈10 min) y luego build_catalog.py. Para cambiar solo el suavizado: fetch_phenology.py --reprofile.
- data/colores_libro.csv: color de flor VERIFICADO en las fotos del libro (2ª ed. 2026) para 116 de 117 especies;
  prioridad máxima. Columna "cambio" indica si se confirmó, corrigió o completó respecto del borrador.
- data/rasgos_por_verificar.csv: rasgos BORRADOR (sus colores ya no se usan) (sobre todo colores) para vacíos del libro. Revisar contra
  las fotos del libro, corregir el CSV y volver a ejecutar el script. Los datos del libro siempre tienen prioridad.
- Excluidos de la identificación: id 105 (encabezado "Cactáceas del…", no es especie) e id 66 (duplicado de Aristolochia vaginans).
- Sensibles: marcadas en la ficha + estados "En Peligro"/"Vulnerable". En exportación PÚBLICA sus coordenadas se
  generalizan a 0,1° (~10 km) y se omite la elevación. La exportación PRIVADA mantiene coordenadas exactas (QGIS).

REGISTROS
IndexedDB del navegador: especie, confianza, método (asistida / asistida_corregida / manual), respuestas y alternativas,
lat/lon/elevación, hábitat, observador, validación, notas y hasta 3 fotos. Exportación GeoJSON, KML y CSV.
Se pierden si se borran los datos del navegador: exportar periódicamente. Mapa: Leaflet + OpenStreetMap (requiere
conexión; las zonas vistas quedan en caché).

LICENCIAS: el modelo se entrenó con fotos CC0 / CC BY / CC BY-NC de iNaturalist (vía GBIF): uso no comercial.
NO INCLUIDO: mapas base offline completos, sincronización, hosting.
