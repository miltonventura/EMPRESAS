/*
  Residenciales y urbanizaciones con nombre - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["landuse"="residential"]["name"](around:15000,13.7342,-89.2864);
  nwr["building"="apartments"]["name"](around:15000,13.7342,-89.2864);
);
out tags center;
