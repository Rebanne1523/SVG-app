# VectorFlow

Editor de vectores para Linux (pensado para CachyOS/Arch; Qt6 + Python) hecho para **fluir en el trabajo**:

- **Capas y carpetas fáciles**: una sola lista, arrastrar y soltar, indicador claro de dónde cae cada cosa.
- **Abre cualquier SVG y PDF** (los PDF se convierten a vectores editables) y guarda **SVG compatible con Inkscape** (las capas se conservan).
- **Controles tipo Photoshop**: atajos de herramientas (`V`, `A`, `P`, `T`, `G`...), escalar/rotar con asas, `Shift` para 45°/proporcional, `Alt` para copiar o desde el centro.
- **Snapping** al mover objetos enteros, puntos, escalar y rotar.
- **Cubo de pintura inteligente**: trabaja sobre la geometría vectorial (no sobre lo que se ve) y cierra huecos pequeños.
- **Líneas de medición** con snap a puntos y bordes, forma de U / L / recta, flechas configurables y texto editable.

---

## Instalación en CachyOS (la forma fácil)

### Opción A — AppImage (recomendada, un solo comando)

```bash
curl -fsSL https://raw.githubusercontent.com/Rebanne1523/SVG-app/main/install.sh | bash
```

Instala VectorFlow solo para tu usuario (sin `sudo`), crea la entrada en el menú de aplicaciones y el comando `vectorflow`.
Para desinstalar: `curl -fsSL https://raw.githubusercontent.com/Rebanne1523/SVG-app/main/install.sh | bash -s -- --uninstall`.

Si el AppImage no arranca, instala estas dependencias del sistema (normalmente ya vienen con KDE):

```bash
sudo pacman -S --needed fuse2 xcb-util-cursor
```

> El AppImage lo genera GitHub Actions al publicar una versión (ver [Publicar una versión](#publicar-una-versión)).
> Puedes también descargarlo a mano desde la pestaña **Releases**, darle permisos (`chmod +x VectorFlow-x86_64.AppImage`) y ejecutarlo, o instalarlo con `./install.sh ruta/al/VectorFlow-x86_64.AppImage`.

### Opción B — Desde el código fuente

```bash
git clone https://github.com/Rebanne1523/SVG-app.git
cd SVG-app
./run.sh
```

La primera vez crea un entorno virtual con las dependencias (`PySide6`, `PyMuPDF`, `shapely`); después abre directamente.
Si prefieres paquetes del sistema en lugar de pip: `sudo pacman -S pyside6 python-shapely python-pymupdf` y luego `python -m vectorflow`.

Abrir archivos directamente: `./run.sh plano.pdf detalle.pdf` o `vectorflow proyecto.vflow`. También puedes arrastrar PDFs/SVGs a la ventana (se añaden como hojas).

---

## Guía rápida

### Proyecto, hojas y guardado

- **Un proyecto = un lienzo con varias hojas** (páginas) colocadas una al lado de otra. Cada hoja tiene su nombre arriba a la izquierda (la etiqueta se puede **arrastrar para mover la hoja entera** con todo lo que lleva).
- **Importar** (`Ctrl+I`, o arrastrar archivos a la ventana): cada PDF/SVG pasa a ser una hoja con **el nombre del archivo**. Si un PDF tiene varias páginas salen como `nombre - 1`, `nombre - 2`… Cada página conserva su tamaño original.
- **Abrir** (`Ctrl+O`) acepta varios archivos a la vez y crea un proyecto nuevo con todas sus hojas.
- El panel de la derecha tiene arriba la lista de **hojas** y debajo las **capas de la hoja seleccionada**: al cambiar de hoja (clic en la lista, en un hueco vacío de la hoja, o seleccionando un objeto) el panel de capas muestra solo lo que hay en ella.
- **Mover entre hojas**: arrastra un vector y suéltalo sobre otra hoja; pasa a pertenecer a esa hoja (va a su capa activa).
- **Posición y tamaño** (barra de arriba): X e Y son la distancia desde la **esquina superior izquierda de la hoja** (0, 0) hasta la esquina superior izquierda de la caja del vector. Poner 0, 0 lo deja pegado a esa esquina. W/H cambian el tamaño desde esa esquina (candado = proporcional).
- **Copiar / pegar**: `Ctrl+V` pega **centrado en el ratón**; `Ctrl+Shift+V` pega **en la misma posición relativa a la hoja** (selecciona primero la hoja de destino): lo que copiaste en la posición (120, 40) de una hoja queda en (120, 40) de la otra.
- **Guardar** (`Ctrl+S`) crea un archivo **`.vflow`** con todas las hojas (dentro hay un SVG por hoja + un manifiesto, así que cada hoja sigue siendo un SVG normal).
- **Última carpeta**: la primera vez, los diálogos abren en **Documentos**. Después recuerdan la **última carpeta que usaste** (abrir, importar, guardar o exportar), también si cierras y vuelves a abrir el programa.

### Exportar (`Ctrl+Shift+E`)

1. Elige **Pages** (páginas) o **Selection only** (solo lo seleccionado, recortado a su caja) y el formato: **PDF vectorial, SVG o PNG**.
2. En *Pages* verás **cada hoja con su vista previa**. Selecciona las que quieras (`Ctrl`/`Shift`+clic).
3. Cada hoja se guarda **con el nombre del archivo que importaste** (`plano.pdf` → `plano.pdf`). Si exportas una sola eliges dónde; si exportas varias eliges una carpeta y salen una por una, cada una con su nombre (si hay nombres repetidos se añade ` (2)`; si ya existen te pregunta antes de reemplazar).
4. Para **unir varias hojas en un solo PDF**: arrastra una miniatura **sobre otra** y se juntan (el PDF resultante tiene esas páginas, cada una con su tamaño y se llama como la primera). "Separate selected" las separa. La unión solo existe para PDF.

### Trazos: combinar y separar

- `Ctrl+K` **combina** varios trazos en un solo trazo compuesto (como una letra con agujeros: cada forma queda como subtrazo y los huecos funcionan).
- `Ctrl+Shift+K` **separa** un trazo compuesto en un trazo por cada subtrazo.

### Capas (panel de la derecha)

| Acción | Cómo |
|---|---|
| Qué es "una capa" | Una carpeta de primer nivel. Las carpetas se pueden anidar sin límite. |
| Orden | **Arriba de la lista = delante**, abajo = detrás. |
| Mover / reorganizar | **Arrastra** filas. La línea azul indica dónde caerá; si sueltas **sobre una carpeta** entra dentro (arriba del todo). Se pueden arrastrar varias filas a la vez (`Ctrl`/`Shift`+clic). |
| Seleccionar | Clic en la fila = seleccionado en el lienzo, y al revés. |
| Dónde dibujo | El texto **"Drawing in: …"** muestra la capa/carpeta de destino (resaltada). Es la carpeta del elemento seleccionado. |
| Ojo / candado | Mostrar-ocultar / bloquear. `Alt`+clic en el ojo = mostrar solo ese. Lo oculto o bloqueado no se puede seleccionar con el ratón. |
| Renombrar | Doble clic o `F2`. |
| Crear | Botones de abajo: nueva capa, nueva carpeta, agrupar (`Ctrl+G`), duplicar (`Ctrl+J`), borrar. Clic derecho = más opciones. |
| Opacidad | Control deslizante sobre la lista. |

En la barra de opciones de **Mover** puedes elegir si el clic selecciona el *elemento exacto* o el *elemento de primer nivel de su capa* (la carpeta completa).

### Herramientas

| Tecla | Herramienta | Notas |
|---|---|---|
| `V` | Mover / Seleccionar | Arrastrar = mover. Asas = escalar. **Pasa el ratón justo fuera de una esquina** y el cursor cambia a rotar. |
| `A` | Selección directa | Puntos, tiradores y segmentos. Doble clic en un punto = suave/esquina; doble clic en un segmento = añadir punto; `Supr` borra puntos. **Rueda sobre un punto**: ver abajo. |
| `P` | Pluma | Clic = esquina, clic-arrastrar = curva, clic en el primer punto = cerrar, `Enter`/`Esc` = terminar. Clic en el extremo de un trazo seleccionado lo continúa. |
| `B` | Lápiz | Trazo libre suavizado a Bézier. |
| `U` `E` `L` | Rectángulo / Elipse / Línea | Radio de esquina en la barra de opciones. |
| `T` | Texto | Clic para crear o editar. |
| `G` | Cubo de pintura | Ver abajo. |
| `I` | Medir | Ver abajo. |
| `H` `Z` | Mano / Zoom | `Espacio` = mano temporal. |

**Seleccionar puntos con la rueda** (herramienta `A`): pon el ratón sobre un punto y haz scroll hacia arriba: se van seleccionando, **hacia ambos lados del trazo**, los puntos conectados al punto desde el que empezaste (hacia abajo se va reduciendo). En la barra de opciones puedes cambiar el modo a *Nearby points (area)*, que selecciona los puntos cercanos como hace Inkscape.

**Modificadores**: `Shift` restringe a 0/45/90° al dibujar o mover, escala proporcional, y rota en pasos de 15° · `Alt` dibuja/escala desde el centro y arrastrando **copia** · flechas = empujar 1 px (`Shift` = 10 px).
**Vista**: rueda = desplazar · `Shift`+rueda = lateral · `Ctrl`/`Alt`+rueda = zoom · `Ctrl+0` ajustar página · `Ctrl+1` 100 %.
**Snapping** (casilla "Snap" o `Ctrl+Shift+;`): a puntos, esquinas, centros y bordes de otros vectores, y al borde/centro de la página. Las líneas rosas muestran la alineación.
**Rotación**: se pega a múltiplos de 15° automáticamente (con `Shift` exactamente) y muestra el ángulo.

### Barra de estilo (arriba)

Relleno, trazo, **grosor**, **tipo de línea** (sólida, rayas, puntos, punto-raya), **final de línea** (plano, redondo, cuadrado), esquinas, **flecha de inicio / final** (triángulo, abierta, círculo, cuadrado, rombo) y su tamaño. Al seleccionar texto o una medición aparece una segunda fila con fuente, tamaño, negrita/cursiva, color, etc. Sin nada seleccionado, cambia el estilo con el que se crearán los siguientes objetos.

### Cubo de pintura inteligente (`G`)

- Se calcula con la **geometría** de todos los trazos visibles (no con los píxeles de la vista): no depende del zoom ni de qué esté tapando qué, así que no quedan "huequitos" por la vista.
- **"Close gaps up to"** (en la barra de opciones, en px del documento): los huecos de contorno menores a ese valor se consideran cerrados. Si el área sigue abierta, el programa te lo dice en la barra de estado.
- El relleno se crea como una forma nueva, justo encima del relleno que había debajo (o al fondo de la capa de destino), y por tanto **detrás de tus líneas**.
- `Alt`+clic recolorea la forma rellena que haya bajo el cursor.
- El color es el de relleno actual de la barra de estilo.

### Medición (`I`)

1. **Clic en el punto A.** El cursor se pega a puntos finales/esquinas y a bordes de otros vectores (círculo rosa + etiqueta indicando qué detectó). Al mover verás el cuadro de selección punteado y la longitud.
2. **Clic en el punto B.** (`Shift` = ángulos de 45°.)
3. **Mueve el ratón** para elegir lado y altura: se forma una **U** en ángulos rectos con una flecha en cada extremo apuntando al punto medido. Cerca de 0 se convierte en una **línea recta**.
4. **Clic final** → aparece un cuadro para escribir la medida (propone la longitud calculada).

**Rueda del ratón**: justo después del 1.er clic voltea la flecha del primer punto; después del 2.º clic, la del segundo. Entre "flecha en la pata" y "flecha siguiendo la línea larga" (así se hacen **L** o líneas rectas). `Esc` / clic derecho cancela.

Para modificarla: selecciónala con **Mover** y en la barra de arriba cambia color y grosor de línea, tipo de línea, tipo/tamaño de flecha, texto (también doble clic), fuente, tamaño y color del texto, lado ("Flip side") y modo de cada extremo.

---

## Formatos

- **Abre / importa**: `.vflow`, `.svg`, `.svgz`, `.pdf` (cada página, una hoja; el PDF se convierte a vectores y el texto pasa a contornos).
- **Guarda**: proyecto `.vflow`. Exporta **PDF vectorial** (uno o varios documentos, con páginas unidas si quieres), **SVG** por hoja (capas = grupos de Inkscape, con nombres, visibilidad y bloqueo) y **PNG**. Las mediciones y flechas se guardan con atributos propios para recuperarlas editables y además se dibujan con elementos SVG estándar.

### Limitaciones conocidas

Dicho con claridad para que no haya sorpresas:

- Los **degradados** se convierten a un color plano; **patrones, filtros y máscaras** se ignoran (los `clipPath` sí se respetan). Solo se cargan imágenes incrustadas.
- El texto de un PDF se importa como contornos (no es editable como texto).
- El relleno del cubo es un polígono (curvas aplanadas con tolerancia muy fina), no reutiliza las curvas originales; en un hueco cerrado por tolerancia puede asomar una pequeña "mejilla" de hasta la mitad de ese valor.
- Un trazo combinado (`Ctrl+K`) usa siempre relleno par-impar, para que los agujeros funcionen.
- El snapping de medición es a la línea central del trazo, no al borde exterior del grosor.
- No hay (todavía) reglas, guías, cuadrícula, operaciones booleanas, degradados ni texto sobre trazado.
- La caja de selección siempre está alineada a los ejes (tras rotar varios objetos la caja vuelve a ser horizontal).
- Probado con tests automáticos y de forma simulada (sin pantalla). **No lo he podido probar sobre un escritorio real de CachyOS**: si ves algo raro, abre un issue.

---

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q      # importación, hojas, guardado, exportación, capas, herramientas, cubo, medición...
```

Estructura: `vectorflow/model.py` (documento y undo), `svg_io.py` (SVG/PDF), `render.py`, `canvas.py` (vista, snap), `tools_*.py` (herramientas), `layers_panel.py`, `props.py` (barra de estilo), `fill.py` (cubo).

### Publicar una versión

El AppImage se construye con `packaging/build-appimage.sh` (PyInstaller + appimagetool). GitHub Actions lo hace al subir una etiqueta:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

También puedes lanzarlo a mano desde **Actions → Tests and AppImage → Run workflow** (el AppImage queda como artefacto), o construirlo localmente con `./packaging/build-appimage.sh` (resultado en `build/`).
