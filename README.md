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

Abrir un archivo directamente: `./run.sh dibujo.svg` o `vectorflow dibujo.pdf`. También puedes arrastrar un archivo a la ventana.

---

## Guía rápida

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
| `A` | Selección directa | Puntos, tiradores y segmentos. Doble clic en un punto = suave/esquina; doble clic en un segmento = añadir punto; `Supr` borra puntos. |
| `P` | Pluma | Clic = esquina, clic-arrastrar = curva, clic en el primer punto = cerrar, `Enter`/`Esc` = terminar. Clic en el extremo de un trazo seleccionado lo continúa. |
| `B` | Lápiz | Trazo libre suavizado a Bézier. |
| `U` `E` `L` | Rectángulo / Elipse / Línea | Radio de esquina en la barra de opciones. |
| `T` | Texto | Clic para crear o editar. |
| `G` | Cubo de pintura | Ver abajo. |
| `I` | Medir | Ver abajo. |
| `H` `Z` | Mano / Zoom | `Espacio` = mano temporal. |

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

- **Abre**: `.svg`, `.svgz`, `.pdf` (una página a elegir; el PDF se convierte a vectores, el texto pasa a contornos).
- **Guarda**: `.svg` / `.svgz` (capas = grupos de Inkscape, con nombres, visibilidad y bloqueo). Las mediciones y flechas se guardan con atributos propios para recuperarlas editables y además se dibujan con elementos SVG estándar.
- **Exporta**: PNG (con escala) y PDF vectorial.

### Limitaciones conocidas

Dicho con claridad para que no haya sorpresas:

- Los **degradados** se convierten a un color plano; **patrones, filtros y máscaras** se ignoran (los `clipPath` sí se respetan). Solo se cargan imágenes incrustadas.
- El texto de un PDF se importa como contornos (no es editable como texto).
- El relleno del cubo es un polígono (curvas aplanadas con tolerancia muy fina), no reutiliza las curvas originales; en un hueco cerrado por tolerancia puede asomar una pequeña "mejilla" de hasta la mitad de ese valor.
- El snapping de medición es a la línea central del trazo, no al borde exterior del grosor.
- No hay (todavía) reglas, guías, cuadrícula, operaciones booleanas, degradados ni texto sobre trazado.
- La caja de selección siempre está alineada a los ejes (tras rotar varios objetos la caja vuelve a ser horizontal).
- Probado con tests automáticos y de forma simulada (sin pantalla). **No lo he podido probar sobre un escritorio real de CachyOS**: si ves algo raro, abre un issue.

---

## Desarrollo

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q      # 22 tests: importación, guardado, capas, herramientas, cubo, medición...
```

Estructura: `vectorflow/model.py` (documento y undo), `svg_io.py` (SVG/PDF), `render.py`, `canvas.py` (vista, snap), `tools_*.py` (herramientas), `layers_panel.py`, `props.py` (barra de estilo), `fill.py` (cubo).

### Publicar una versión

El AppImage se construye con `packaging/build-appimage.sh` (PyInstaller + appimagetool). GitHub Actions lo hace al subir una etiqueta:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

También puedes lanzarlo a mano desde **Actions → Tests and AppImage → Run workflow** (el AppImage queda como artefacto), o construirlo localmente con `./packaging/build-appimage.sh` (resultado en `build/`).
