/*
  Empresas de alimentos y bebidas
  28 distritos: AMSS y la franja costera de La Libertad.
  Pegar en https://overpass-turbo.eu -> Ejecutar -> Exportar (GeoJSON / CSV / GPX)
  Datos (c) colaboradores de OpenStreetMap, licencia ODbL
*/
[out:json][timeout:600];
rel(13.00,-90.30,14.60,-87.60)["boundary"="administrative"]["admin_level"!="2"]["admin_level"!="4"]["name"~"^(San Salvador|Ayutuxtepeque|Mejicanos|Cuscatancingo|(Ciudad )?Delgado|Apopa|Nejapa|Ilopango|San Mart[ií]n|Soyapango|Tonacatepeque|San Marcos|Panchimalco|Rosario de Mora|Santiago Texacuangos|Santo Tom[áa]s|Antiguo Cuscatl[áa]n|Huiz[úu]car|Nuevo Cuscatl[áa]n|San Jos[eé] Villa ?[Nn]ueva|Zaragoza|Chiltiup[áa]n|Jicalapa|La Libertad|Tamanique|Teotepeque|Santa Tecla|Nueva San Salvador|Comasagua)$"]->.d;
.d map_to_area ->.zona;
(
  nwr["shop"~"^(bakery|pastry|butcher|deli|confectionery|greengrocer|seafood|dairy|alcohol|beverages|supermarket|wholesale|convenience|frozen_food|health_food|spices|tea|water)$"](area.zona);
  nwr["craft"~"^(bakery|brewery|distillery|winery|confectionery|caterer|dairy|butcher)$"](area.zona);
  nwr["amenity"~"^(bar|pub|biergarten|ice_cream)$"](area.zona);
  nwr["industrial"~"^(food|brewery|slaughterhouse)$"](area.zona);
  nwr["man_made"="works"]["product"~"food|drink|beverage|milk|dairy|meat|bread|sugar|beer|water",i](area.zona);
  nwr["name"~"alimentos|bebidas|embotellador|cervecer|l[áa]cteos|panificadora|agroindustri|molinos? de|distribuidora de alimentos",i][!"highway"](area.zona);
);
out tags center;
