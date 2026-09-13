/*
  Agricultura, fincas y agroservicios - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["shop"~"^(agrarian|farm|garden_centre)$"](around:15000,13.7342,-89.2864);
  nwr["craft"~"^(agricultural_engines|distillery|winery)$"](around:15000,13.7342,-89.2864);
  nwr["landuse"~"^(farmland|orchard|vineyard|greenhouse_horticulture|plant_nursery|meadow)$"]["name"](around:15000,13.7342,-89.2864);
  nwr["place"="farm"](around:15000,13.7342,-89.2864);
  nwr["crop"](around:15000,13.7342,-89.2864);
  nwr["product"~"coffee|caf",i]["name"](around:15000,13.7342,-89.2864);
  nwr["man_made"="works"]["name"](around:15000,13.7342,-89.2864);
);
out tags center;
