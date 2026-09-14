/*
  Cafe: cafetales, beneficios, tostadurias y cafeterias - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["amenity"="cafe"](around:15000,13.7342,-89.2864);
  nwr["shop"="coffee"](around:15000,13.7342,-89.2864);
  nwr["craft"="coffee_roastery"](around:15000,13.7342,-89.2864);
  nwr["cuisine"~"coffee",i](around:15000,13.7342,-89.2864);
  nwr["crop"~"coffee|caf",i](around:15000,13.7342,-89.2864);
  nwr["produce"~"coffee|caf",i](around:15000,13.7342,-89.2864);
  nwr["product"~"coffee|caf",i](around:15000,13.7342,-89.2864);
  nwr["trees"~"coffee",i](around:15000,13.7342,-89.2864);
  nwr["name"~"caf[eé]|cafetal|beneficio|tostadur|finca ",i][!"highway"](around:15000,13.7342,-89.2864);
);
out tags center;
