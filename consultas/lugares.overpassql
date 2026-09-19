/*
  Lugares poblados (place=*)
  Departamentos de San Salvador y La Libertad, con sus municipios y distritos.
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV)
  OJO: para las etiquetas grandes conviene reducir el area antes de ejecutar.
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:800];
rel(13.00,-90.30,14.60,-87.60)["boundary"="administrative"]["admin_level"!="2"]["name"~"^(San Salvador|La Libertad)$"]->.dep;
.dep map_to_area ->.zona;
(
  nwr["place"](area.zona);
);
out tags center;
