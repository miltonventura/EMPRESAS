/*
  Restaurantes y comercios de alimentos - zona del volcan de San Salvador (El Salvador)
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Centro: crater El Boqueron 13.7342, -89.2864 | Radio: 15 km
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:180];
(
  nwr["amenity"~"^(restaurant|fast_food|cafe|bar|pub|ice_cream|food_court|biergarten)$"](around:15000,13.7342,-89.2864);
  nwr["shop"~"^(bakery|coffee|deli|pastry|butcher|greengrocer|convenience|supermarket)$"](around:15000,13.7342,-89.2864);
);
out tags center;
