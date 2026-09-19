/*
  Edificios (building=*)
  Departamentos de San Salvador y La Libertad, con sus municipios y distritos.
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV)
  OJO: para las etiquetas grandes conviene reducir el area antes de ejecutar.
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:800];
rel(13.00,-90.30,14.60,-87.60)["boundary"="administrative"]["admin_level"!="2"]["name"~"^(San Salvador|La Libertad)$"]->.dep;
.dep map_to_area ->.zona;
(
  nwr["building"]["name"](area.zona);
  nwr["building"~"^(commercial|retail|industrial|warehouse|office|hotel|school|university|hospital|church|cathedral|chapel|mosque|temple|government|civic|public|train_station|stadium|sports_hall|supermarket|kiosk|construction|farm|barn|greenhouse|hangar)$"](area.zona);
);
out tags center;
