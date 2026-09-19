#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga registros de OpenStreetMap para los departamentos de San Salvador y
La Libertad (El Salvador), con todos sus municipios y distritos.

Trae TODOS los valores de cada etiqueta de OSM pedida: comercios (shop),
oficinas y empresas (office), talleres (craft), industria (industrial),
servicios (amenity), ocio (leisure), turismo (tourism), clubes (club),
edificios (building), uso del suelo (landuse), lugares poblados (place),
naturales (natural), historicos (historic) e infraestructura (man_made).

La marca (brand), el tipo de cocina (cuisine) y el deporte (sport) no son
grupos aparte: viajan como columnas de cada registro.

Uso:   pip install requests
       python3 descargar.py

Deja un CSV por grupo en la carpeta 'datos', mas un CSV con todo junto y un
GeoJSON. Cada registro queda etiquetado con su departamento, municipio y
distrito.

Datos (c) colaboradores de OpenStreetMap, licencia ODbL.
"""

import collections
import csv
import json
import os
import time

import requests

# ---------------------------------------------------------------- AJUSTES ---
CARPETA = "datos"   # donde se guardan los resultados

# Departamentos a consultar. El script descubre solo los municipios y distritos
# que hay dentro de ellos; no hay que enumerarlos.
DEPARTAMENTOS = ["San Salvador", "La Libertad"]

# Grupos a descargar: (nombre del archivo, etiqueta de OSM).
# Comenta con # la linea de un grupo que no quieras bajar.
GRUPOS = [
    ("comercios",       "shop"),
    ("oficinas",        "office"),
    ("talleres",        "craft"),
    ("industria",       "industrial"),
    ("servicios",       "amenity"),
    ("ocio",            "leisure"),
    ("turismo",         "tourism"),
    ("clubes",          "club"),
    ("uso_del_suelo",   "landuse"),
    ("lugares",         "place"),
    ("naturales",       "natural"),
    ("historicos",      "historic"),
    ("infraestructura", "man_made"),
    ("edificios",       "building"),
]

# Los edificios son, de lejos, el grupo mas grande: en estos dos departamentos
# puede haber cientos de miles de casas mapeadas. Con False se traen solo los
# edificios con nombre o de uso no residencial, que es lo util para un censo
# de negocios. Ponlo en True si de verdad quieres cada casa.
EDIFICIOS_COMPLETOS = False

# Grupos que se consultan directamente distrito por distrito, sin intentar
# primero la consulta grande, porque se sabe que no cabe de una sola vez.
GRUPOS_PESADOS = {"edificios"}

# Si el total supera este numero de registros, se omite el GeoJSON combinado
# (un archivo de ese tamano no lo abre ningun visor comodamente).
LIMITE_GEOJSON = 200000

SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Rectangulo que contiene a El Salvador; acota la busqueda de los limites
# administrativos para que no aparezcan homonimos de otros paises.
BBOX_PAIS = "13.00,-90.30,14.60,-87.60"

# Niveles administrativos por debajo del departamento (municipios y distritos).
NIVELES_INTERNOS = "^(5|6|7|8|9|10)$"

TIMEOUT_CONSULTA = 800   # segundos que se le piden a Overpass
PASO_REJILLA = 0.005     # ~550 m; agrupa los segmentos de frontera por latitud

COLUMNAS = ["grupo", "clave", "valor", "etiqueta_es", "nombre", "marca",
            "operador", "departamento", "municipio", "distrito",
            "latitud", "longitud", "direccion", "ciudad", "telefono", "correo",
            "sitio_web", "horario", "cocina", "cocina_es", "deporte",
            "deporte_es", "tipo_club", "tipo_club_es",
            "osm_tipo", "osm_id", "url_osm"]

# Traduccion de los valores de OSM al español salvadoreño. Si un valor no esta
# aqui, la columna etiqueta_es queda vacia y el valor crudo sigue en la columna
# 'valor'. Se puede ampliar libremente.
ETIQUETAS = {
    "amenity": {
        "adult_gaming_centre": "salón de tragamonedas",
        "animal_boarding": "pensión de mascotas", "animal_breeding": "criadero",
        "animal_shelter": "albergue de animales",
        "animal_training": "adiestramiento de animales",
        "arts_centre": "centro cultural", "atm": "cajero automático",
        "baby_hatch": "buzón de bebés", "baking_oven": "horno de pan", "bank": "banco",
        "bar": "bar", "bbq": "parrilla pública", "bench": "banca",
        "bicycle_parking": "estacionamiento de bicicletas",
        "bicycle_rental": "alquiler de bicicletas",
        "bicycle_repair_station": "estación de reparación de bicicletas",
        "bicycle_wash": "lavado de bicicletas",
        "biergarten": "cervecería al aire libre", "boat_rental": "alquiler de lanchas",
        "boat_sharing": "lanchas compartidas", "brothel": "prostíbulo",
        "bureau_de_change": "casa de cambio", "bus_station": "terminal de buses",
        "cafe": "cafetería", "car_rental": "alquiler de autos",
        "car_sharing": "autos compartidos", "car_wash": "lavado de autos",
        "casino": "casino", "charging_station": "estación de carga eléctrica",
        "childcare": "guardería", "cinema": "cine",
        "clinic": "clínica o unidad de salud", "clock": "reloj público",
        "college": "instituto tecnológico", "community_centre": "casa comunal",
        "compressed_air": "aire para llantas",
        "conference_centre": "centro de convenciones", "courthouse": "juzgado",
        "coworking_space": "coworking", "crematorium": "crematorio",
        "dancing_school": "escuela de baile", "dentist": "dentista",
        "dive_centre": "centro de buceo", "doctors": "consultorio",
        "dog_toilet": "baño para perros", "dojo": "dojo de artes marciales",
        "dressing_room": "vestidor", "drinking_water": "bebedero",
        "driver_training": "pista de manejo", "driving_school": "escuela de manejo",
        "events_venue": "salón de eventos",
        "exhibition_centre": "centro de exposiciones", "fast_food": "comida rápida",
        "ferry_terminal": "terminal de ferry", "festival_grounds": "campo de ferias",
        "fire_station": "bomberos", "first_aid_school": "escuela de primeros auxilios",
        "food_court": "plaza de comidas", "fountain": "fuente ornamental",
        "fuel": "gasolinera", "funeral_hall": "funeraria",
        "gambling": "casa de apuestas", "give_box": "caja de intercambio gratuito",
        "grave_yard": "cementerio", "grit_bin": "depósito de arena o sal",
        "hospital": "hospital", "hunting_stand": "puesto de caza",
        "ice_cream": "sorbetería", "internet_cafe": "ciber (café internet)",
        "kindergarten": "kínder", "kitchen": "cocina comunitaria",
        "language_school": "escuela de idiomas", "letter_box": "buzón particular",
        "library": "biblioteca", "loading_dock": "muelle de carga",
        "lounge": "sala VIP", "lounger": "silla de playa",
        "love_hotel": "autohotel (motel de paso)",
        "luggage_locker": "casilleros de equipaje",
        "mailroom": "sala de correspondencia", "marketplace": "mercado",
        "mobile_money_agent": "agente de dinero móvil",
        "monastery": "monasterio o convento", "money_transfer": "remesas",
        "mortuary": "morgue", "motorcycle_parking": "estacionamiento de motos",
        "motorcycle_rental": "alquiler de motos", "music_school": "escuela de música",
        "music_venue": "sala de conciertos", "nightclub": "discoteca",
        "nursing_home": "asilo de ancianos", "parcel_locker": "casillero de paquetes",
        "parking": "estacionamiento", "parking_entrance": "entrada de estacionamiento",
        "parking_space": "espacio de estacionamiento",
        "payment_centre": "centro de pagos", "payment_terminal": "terminal de pago",
        "pharmacy": "farmacia", "photo_booth": "cabina de fotos",
        "place_of_mourning": "sala de velación", "place_of_worship": "lugar de culto",
        "planetarium": "planetario", "police": "policía", "post_box": "buzón",
        "post_depot": "centro de distribución postal", "post_office": "correos",
        "prep_school": "academia de refuerzo escolar", "prison": "cárcel", "pub": "pub",
        "public_bath": "casa de baños o balneario",
        "public_bookcase": "intercambio de libros",
        "ranger_station": "caseta de guardaparques", "reception_desk": "recepción",
        "recycling": "reciclaje", "refugee_site": "campamento de refugiados",
        "register_office": "registro civil",
        "research_institute": "instituto de investigación", "restaurant": "restaurante",
        "sanitary_dump_station": "estación de descarga sanitaria", "school": "escuela",
        "security_booth": "caseta de vigilancia", "shelter": "refugio techado",
        "shower": "duchas", "smoking_area": "área de fumadores",
        "social_centre": "centro social",
        "social_facility": "centro de asistencia social", "stage": "escenario",
        "stripclub": "club de striptease", "studio": "estudio de radio, TV o grabación",
        "surf_school": "escuela de surf", "swingerclub": "club swinger",
        "taxi": "parada de taxis", "telephone": "teléfono público", "theatre": "teatro",
        "toilets": "baños públicos", "townhall": "alcaldía", "toy_library": "ludoteca",
        "traffic_park": "parque de educación vial",
        "training": "centro de capacitación", "trolley_bay": "corral de carritos",
        "university": "universidad", "vacuum_cleaner": "aspiradora para vehículos",
        "vehicle_inspection": "revisión vehicular",
        "vending_machine": "máquina expendedora", "veterinary": "veterinaria",
        "waste_basket": "basurero", "waste_disposal": "contenedor de basura",
        "waste_transfer_station": "estación de transferencia de desechos",
        "water_point": "toma de agua potable", "watering_place": "abrevadero",
        "weighbridge": "báscula de camiones",
    },
    "building": {
        "annexe": "anexo", "apartments": "apartamentos", "barn": "granero",
        "barracks": "cuartel", "beach_hut": "caseta de playa",
        "boathouse": "casa de botes", "bridge": "pasarela cubierta",
        "bungalow": "bungaló", "bunker": "búnker", "cabin": "cabaña",
        "carport": "cochera", "cathedral": "catedral", "chapel": "capilla",
        "church": "iglesia", "civic": "edificio comunal", "college": "instituto",
        "commercial": "comercial", "construction": "en construcción",
        "container": "contenedor", "cowshed": "establo de vacas",
        "detached": "casa individual", "dormitory": "residencia estudiantil",
        "farm": "casa de finca", "farm_auxiliary": "construcción agrícola",
        "fire_station": "estación de bomberos", "garage": "garaje",
        "garages": "garajes", "garbage_shed": "caseta de basura",
        "gatehouse": "portería", "government": "edificio de gobierno",
        "grandstand": "gradería", "greenhouse": "invernadero",
        "guardhouse": "caseta de vigilancia", "hangar": "hangar",
        "hospital": "hospital", "hotel": "hotel", "house": "casa",
        "houseboat": "casa flotante", "hut": "champa", "industrial": "industrial",
        "kindergarten": "kínder", "kingdom_hall": "salón del reino", "kiosk": "kiosco",
        "livestock": "galera de animales", "manufacture": "fábrica",
        "monastery": "monasterio", "mosque": "mezquita", "museum": "museo",
        "office": "oficinas", "outbuilding": "construcción anexa",
        "parking": "estacionamiento", "pavilion": "pabellón deportivo",
        "presbytery": "casa parroquial", "public": "edificio público",
        "religious": "edificio religioso", "residential": "residencial",
        "retail": "local comercial", "roof": "techado sin paredes", "ruins": "ruinas",
        "school": "escuela", "semidetached_house": "casa dúplex",
        "service": "caseta de servicio", "shed": "cobertizo", "shrine": "ermita",
        "silo": "silo", "sports_centre": "centro deportivo",
        "sports_hall": "gimnasio techado", "stable": "caballeriza",
        "stadium": "estadio", "static_caravan": "casa móvil", "stilt_house": "palafito",
        "storage_tank": "tanque de almacenamiento", "sty": "chiquero",
        "supermarket": "supermercado", "synagogue": "sinagoga",
        "tech_cab": "caseta técnica", "temple": "templo", "tent": "carpa",
        "terrace": "hilera de casas", "toilets": "baños", "tower": "torre",
        "train_station": "estación de tren",
        "transformer_tower": "torre de transformador",
        "transportation": "terminal de transporte", "university": "universidad",
        "warehouse": "bodega", "water_tower": "tanque elevado", "yes": "edificio",
    },
    "club": {
        "amateur_radio": "club de radioaficionados", "art": "club de arte",
        "astronomy": "club de astronomía", "automobile": "club de autos",
        "aviation": "club de aviación", "bicycle": "club de ciclismo",
        "board_games": "club de juegos de mesa",
        "card_games": "club de juegos de cartas",
        "charity": "club de beneficencia (Rotary, Leones)", "chess": "club de ajedrez",
        "cinema": "cineclub", "computer": "club de computación",
        "culture": "club cultural", "dog": "club canino",
        "environment_protection": "club ecologista", "ethnic": "club étnico",
        "fan": "club de fans", "fishing": "club de pesca",
        "freemasonry": "logia masónica", "game": "club de juegos",
        "golf": "club de golf", "history": "club de historia",
        "hunting": "club de caza", "motorcycle": "club de motos",
        "music": "club de música", "nature": "club de naturaleza",
        "photography": "club de fotografía", "politics": "club político",
        "religion": "club religioso", "sailing": "club náutico", "scout": "grupo scout",
        "scuba_diving": "club de buceo", "shooting": "club de tiro",
        "social": "club social", "sport": "club deportivo",
        "student": "club estudiantil", "theatre": "club de teatro",
        "tourism": "club de turismo", "veterans": "club de veteranos",
        "yachting": "club de yates", "yes": "club (sin especificar)",
        "youth": "club juvenil", "youth_movement": "movimiento juvenil",
    },
    "craft": {
        "agricultural_engines": "taller de maquinaria agrícola",
        "atelier": "taller de artista", "bag_repair": "reparación de bolsos y maletas",
        "bakery": "panadería artesanal", "basket_maker": "cestería",
        "beekeeper": "apicultor", "blacksmith": "herrería",
        "boatbuilder": "constructor de lanchas", "bookbinder": "encuadernación",
        "brewery": "cervecería artesanal", "builder": "albañilería",
        "cabinet_maker": "ebanistería", "candlemaker": "fabricación de velas",
        "car_painter": "pintura automotriz", "carpenter": "carpintería",
        "carpet_cleaner": "lavado de alfombras y muebles",
        "carpet_layer": "instalación de alfombras", "caterer": "servicio de banquetes",
        "cleaning": "servicio de limpieza", "clothes_mending": "arreglos de ropa",
        "confectionery": "repostería", "dental_technician": "laboratorio dental",
        "distillery": "destilería", "door_construction": "fabricación de puertas",
        "dressmaker": "modistería", "electrician": "electricista",
        "electronics_repair": "reparación electrónica",
        "elevator": "instalación de elevadores", "embroiderer": "bordados",
        "engraver": "grabado", "fence_maker": "fabricación de cercas y portones",
        "floorer": "instalación de pisos", "gardener": "jardinería",
        "glaziery": "vidriería", "goldsmith": "orfebrería",
        "grinding_mill": "molino de granos", "handicraft": "artesanías",
        "hvac": "aire acondicionado", "insulation": "aislamiento térmico",
        "interior_decorator": "decoración de interiores",
        "interior_work": "acabados de interiores", "jeweller": "joyero",
        "joiner": "carpintería de obra", "key_cutter": "duplicado de llaves",
        "leather": "marroquinería", "locksmith": "cerrajería",
        "luthier": "luthier (instrumentos de cuerda)",
        "metal_construction": "estructuras metálicas",
        "musical_instrument": "taller de instrumentos musicales", "optician": "óptica",
        "painter": "pintor", "parquet_layer": "instalación de piso de madera",
        "paver": "adoquinado", "pest_control": "fumigación y control de plagas",
        "photographer": "fotógrafo",
        "photographic_laboratory": "laboratorio fotográfico",
        "photovoltaic": "instalación de paneles solares",
        "piano_tuner": "afinador de pianos", "plasterer": "repello y afinado",
        "plumber": "plomería", "pottery": "alfarería", "printer": "imprenta",
        "restoration": "restauración", "roofer": "techador", "saddler": "talabartería",
        "sawmill": "aserradero", "scaffolder": "montaje de andamios",
        "sculptor": "escultor", "shoemaker": "zapatero", "signmaker": "rotulación",
        "stonemason": "cantería", "sun_protection": "toldos y persianas",
        "tailor": "sastrería", "tiler": "enchapado de azulejos",
        "tinsmith": "hojalatería", "turner": "tornero", "upholsterer": "tapicería",
        "watchmaker": "relojería", "water_well_drilling": "perforación de pozos",
        "weaver": "tejeduría", "welder": "soldadura",
        "window_construction": "ventanería", "winery": "vinícola",
    },
    "cuisine": {
        "american": "americana", "arab": "árabe", "argentinian": "argentina",
        "asian": "asiática", "bagel": "bagels", "bakery": "panadería",
        "barbecue": "barbacoa (BBQ)", "brazilian": "brasileña",
        "breakfast": "desayunos", "brunch": "brunch", "bubble_tea": "bubble tea",
        "buffet": "bufé", "burger": "hamburguesas", "burrito": "burritos",
        "cake": "pasteles", "caribbean": "caribeña", "chicken": "pollo",
        "chinese": "china", "chocolate": "chocolatería", "coffee_shop": "cafetería",
        "colombian": "colombiana", "crepe": "crepas", "cuban": "cubana",
        "curry": "curry", "dessert": "postres", "donut": "donas",
        "empanada": "empanadas", "fine_dining": "alta cocina", "fish": "pescado",
        "fish_and_chips": "pescado con papas fritas", "french": "francesa",
        "fried_chicken": "pollo frito", "fried_food": "frituras",
        "frozen_yogurt": "yogurt helado", "fusion": "fusión", "german": "alemana",
        "greek": "griega", "grill": "parrilla", "hot_dog": "hot dogs",
        "ice_cream": "helados (sorbetes)", "indian": "india",
        "international": "internacional", "italian": "italiana", "japanese": "japonesa",
        "juice": "jugos", "kebab": "kebab", "korean": "coreana",
        "latin_american": "latinoamericana", "lebanese": "libanesa",
        "local": "comida local", "lunch": "almuerzos", "mediterranean": "mediterránea",
        "mexican": "mexicana", "milkshake": "malteadas", "noodle": "fideos",
        "pancake": "panqueques", "pasta": "pasta", "pastry": "repostería",
        "peruvian": "peruana", "pizza": "pizza", "portuguese": "portuguesa",
        "pupusa": "pupusas (pupusería)", "ramen": "ramen", "regional": "típica",
        "salad": "ensaladas", "salvadoran": "salvadoreña", "sandwich": "sándwiches",
        "sausage": "salchichas", "seafood": "mariscos", "shawarma": "shawarma",
        "smoothie": "licuados", "soup": "sopas", "spanish": "española",
        "steak_house": "carnes (steak house)", "sushi": "sushi", "tacos": "tacos",
        "tapas": "tapas", "tea": "té", "tex-mex": "tex-mex", "thai": "tailandesa",
        "turkish": "turca", "vegan": "vegana", "vegetarian": "vegetariana",
        "venezuelan": "venezolana", "vietnamese": "vietnamita", "waffle": "waffles",
        "wings": "alitas",
    },
    "historic": {
        "aircraft": "avión histórico", "anchor": "ancla histórica",
        "aqueduct": "acueducto histórico", "archaeological_site": "sitio arqueológico",
        "battlefield": "campo de batalla", "boundary_stone": "mojón limítrofe",
        "bridge": "puente histórico", "building": "edificio histórico",
        "bunker": "búnker histórico", "cannon": "cañón histórico", "castle": "castillo",
        "castle_wall": "muralla de castillo", "chapel": "capilla histórica",
        "church": "iglesia histórica", "city_gate": "puerta de la ciudad",
        "citywalls": "murallas de la ciudad", "farm": "finca histórica",
        "fort": "fuerte o fortaleza", "house": "casa histórica",
        "locomotive": "locomotora histórica", "manor": "casco de hacienda",
        "memorial": "memorial o placa conmemorativa", "milestone": "mojón kilométrico",
        "mine": "mina histórica", "mine_adit": "socavón de mina",
        "mine_shaft": "pozo de mina", "monastery": "convento o monasterio",
        "monument": "monumento", "railway_car": "vagón de tren histórico",
        "railway_station": "estación de tren histórica", "ruins": "ruinas",
        "ship": "barco histórico", "stone": "piedra histórica",
        "tank": "tanque de guerra", "tomb": "tumba monumental",
        "tower": "torre histórica", "wayside_chapel": "capilla de camino",
        "wayside_cross": "cruz de camino", "wayside_shrine": "nicho o altar de camino",
        "wreck": "restos de naufragio", "yes": "sitio histórico",
    },
    "industrial": {
        "aluminium_smelting": "fundición de aluminio", "auto_wrecker": "deshuesadero",
        "bakery": "panificadora", "brewery": "cervecería", "brickyard": "ladrillera",
        "construction_company": "constructora", "depot": "plantel",
        "distributor": "distribuidora", "factory": "fábrica",
        "food_processing": "procesadora de alimentos",
        "furniture": "fábrica de muebles", "gas": "industria del gas",
        "gas_storage": "almacenamiento de gas", "gasworks": "planta de gas",
        "grinding_mill": "molino", "heating_station": "central de calefacción urbana",
        "ice_factory": "fábrica de hielo", "logistics": "centro logístico",
        "machine_shop": "taller de torno", "metal_processing": "metalmecánica",
        "mine": "mina", "oil": "petrolera", "oil_mill": "aceitera",
        "port": "puerto industrial", "quarry": "cantera", "recycling": "recicladora",
        "refinery": "refinería", "rice_mill": "arrocera", "salt_pond": "salinera",
        "sawmill": "aserradero", "scrap_yard": "chatarrera", "shipyard": "astillero",
        "slaughterhouse": "rastro", "steel_mill": "acería",
        "steelmaking": "siderúrgica", "timber": "maderera", "warehouse": "bodega",
        "well_cluster": "campo de pozos", "wellsite": "pozo petrolero",
    },
    "landuse": {
        "allotments": "huertos comunitarios", "animal_keeping": "crianza de animales",
        "apiary": "apiario", "aquaculture": "camaroneras o criaderos de peces",
        "basin": "laguna de retención", "brownfield": "terreno por reurbanizar",
        "cemetery": "cementerio", "churchyard": "predio de iglesia",
        "commercial": "zona comercial", "conservation": "área de conservación",
        "construction": "terreno en construcción", "depot": "depósito de vehículos",
        "education": "zona educativa", "fairground": "campo ferial",
        "farm": "finca o granja", "farmland": "cultivos", "farmyard": "casco de finca",
        "flowerbed": "arriate", "forest": "bosque", "forestry": "manejo forestal",
        "garages": "garajes", "grass": "grama", "greenfield": "terreno por urbanizar",
        "greenhouse_horticulture": "invernaderos", "harbour": "puerto",
        "industrial": "zona industrial", "institutional": "zona institucional",
        "landfill": "relleno sanitario", "logging": "área de tala", "meadow": "potrero",
        "military": "zona militar", "orchard": "huerto de frutales",
        "peat_cutting": "extracción de turba", "plant_nursery": "vivero",
        "port": "zona portuaria", "quarry": "cantera", "railway": "zona ferroviaria",
        "recreation_ground": "área recreativa", "religious": "terreno religioso",
        "reservoir": "embalse", "residential": "zona residencial",
        "retail": "comercio al detalle", "salt_pond": "salinera",
        "village_green": "área verde comunal", "vineyard": "viñedo",
        "winter_sports": "deportes de invierno",
    },
    "leisure": {
        "adult_gaming_centre": "sala de tragamonedas",
        "amusement_arcade": "sala de videojuegos", "bandstand": "kiosco de música",
        "bathing_place": "sitio para bañarse", "beach_resort": "balneario",
        "bird_hide": "observatorio de aves", "bleachers": "graderías",
        "bowling_alley": "boliche", "common": "terreno comunal",
        "dance": "salón de baile", "disc_golf_course": "campo de disc golf",
        "dog_park": "parque para perros", "escape_game": "sala de escape",
        "firepit": "área de fogata", "fishing": "zona de pesca",
        "fitness_centre": "gimnasio",
        "fitness_station": "aparatos de ejercicio al aire libre", "garden": "jardín",
        "golf_course": "campo de golf", "hackerspace": "espacio maker",
        "horse_riding": "centro de equitación", "ice_rink": "pista de hielo",
        "indoor_play": "centro de juegos infantiles", "marina": "marina",
        "miniature_golf": "minigolf", "nature_reserve": "reserva natural",
        "outdoor_seating": "mesas al aire libre", "paddling_pool": "piscina infantil",
        "park": "parque", "picnic_table": "mesa de picnic", "pitch": "cancha",
        "playground": "parque infantil", "recreation_ground": "zona recreativa",
        "resort": "complejo turístico", "sauna": "sauna", "schoolyard": "patio escolar",
        "slipway": "rampa para lanchas", "social_club": "club social",
        "sports_centre": "centro deportivo", "sports_hall": "cancha techada",
        "stadium": "estadio", "summer_camp": "campamento vacacional",
        "swimming_area": "área para nadar", "swimming_pool": "piscina",
        "tanning_salon": "salón de bronceado", "track": "pista de atletismo",
        "trampoline_park": "parque de trampolines",
        "village_green": "área verde del pueblo", "water_park": "parque acuático",
        "wildlife_hide": "observatorio de fauna",
    },
    "man_made": {
        "adit": "bocamina", "beacon": "baliza", "breakwater": "rompeolas",
        "bridge": "puente (estructura)", "bunker_silo": "silo de forraje",
        "chimney": "chimenea", "communications_tower": "torre de telecomunicaciones",
        "cooling_tower": "torre de enfriamiento", "courtyard": "patio", "crane": "grúa",
        "cross": "cruz", "cutline": "brecha forestal", "dyke": "dique de contención",
        "embankment": "terraplén", "flagpole": "asta de bandera",
        "gantry": "pórtico de señalización", "gasometer": "gasómetro",
        "goods_conveyor": "banda transportadora", "groyne": "espigón",
        "kiln": "horno industrial", "lighthouse": "faro", "manhole": "pozo de registro",
        "mast": "antena", "mineshaft": "pozo de mina",
        "monitoring_station": "estación de monitoreo", "obelisk": "obelisco",
        "petroleum_well": "pozo petrolero", "pier": "muelle", "pipeline": "tubería",
        "planter": "jardinera", "pump": "bomba de agua",
        "pumping_station": "estación de bombeo", "quay": "muelle de atraque",
        "reservoir_covered": "cisterna", "satellite_dish": "antena parabólica",
        "silo": "silo", "spoil_heap": "escombrera",
        "storage_tank": "tanque de almacenamiento",
        "street_cabinet": "gabinete de servicios",
        "surveillance": "cámara de vigilancia", "survey_point": "punto geodésico",
        "tower": "torre", "tunnel": "túnel", "utility_pole": "poste de servicios",
        "wastewater_plant": "planta de tratamiento de aguas residuales",
        "water_tap": "chorro público", "water_tower": "tanque de agua elevado",
        "water_well": "pozo de agua", "water_works": "planta potabilizadora",
        "watermill": "molino de agua", "wildlife_crossing": "paso de fauna",
        "windmill": "molino de viento", "windpump": "molino de bombeo de agua",
        "works": "fábrica",
    },
    "natural": {
        "arch": "arco natural", "arete": "arista", "bare_rock": "roca desnuda",
        "bay": "bahía", "beach": "playa", "blockfield": "campo de bloques",
        "blowhole": "bufadero", "cape": "punta o cabo",
        "cave_entrance": "cueva (entrada)", "cliff": "acantilado",
        "coastline": "línea de costa", "dune": "duna", "earth_bank": "talud",
        "fell": "pastizal de montaña", "fumarole": "fumarola (ausol)",
        "geyser": "géiser", "glacier": "glaciar", "grassland": "pastizal",
        "gully": "cárcava", "heath": "brezal", "hill": "loma",
        "hot_spring": "aguas termales", "isthmus": "istmo", "moor": "páramo",
        "mountain_range": "cordillera", "mud": "lodazal", "peak": "cerro",
        "peninsula": "península", "plateau": "meseta", "reef": "arrecife",
        "ridge": "cresta", "rock": "peñasco o formación rocosa",
        "saddle": "collado o portillo", "sand": "arena", "scree": "pedregal",
        "scrub": "matorral", "shingle": "playa de guijarros",
        "shoal": "bajo o banco de arena", "shrub": "arbusto",
        "shrubbery": "arbustos ornamentales", "sinkhole": "dolina o sumidero",
        "spring": "manantial (nacimiento de agua)", "stone": "piedra o bloque suelto",
        "strait": "estrecho", "tree": "árbol", "tree_row": "hilera de árboles",
        "tree_stump": "tocón", "tundra": "tundra", "valley": "valle",
        "volcano": "volcán", "water": "cuerpo de agua (lago, laguna)",
        "wetland": "humedal (incluye manglar)", "wood": "bosque",
    },
    "office": {
        "accountant": "contadores", "adoption_agency": "agencia de adopción",
        "advertising_agency": "publicidad", "airline": "aerolínea",
        "architect": "arquitectos", "association": "asociación",
        "charity": "organización de beneficencia", "company": "empresa",
        "construction_company": "constructora", "consulting": "consultoría",
        "courier": "courier", "coworking": "coworking",
        "diplomatic": "embajada o consulado",
        "educational_institution": "institución educativa",
        "employment_agency": "agencia de empleo",
        "energy_supplier": "distribuidora eléctrica", "engineer": "ingeniería",
        "estate_agent": "inmobiliaria", "financial": "servicios financieros",
        "financial_advisor": "asesor financiero", "forestry": "oficina forestal",
        "foundation": "fundación", "geodesist": "geodesia", "government": "gobierno",
        "graphic_design": "diseño gráfico", "guide": "guía turístico",
        "harbour_master": "capitanía de puerto", "insurance": "aseguradora",
        "insurance_adjuster": "ajustador de seguros", "it": "tecnología",
        "lawyer": "abogados", "logistics": "logística",
        "mortgage": "créditos hipotecarios", "moving_company": "mudanzas",
        "newspaper": "periódico", "ngo": "ONG", "notary": "notaría",
        "political_party": "partido político",
        "private_investigator": "investigador privado",
        "property_management": "administradora de inmuebles", "publisher": "editorial",
        "quango": "ente autónomo", "religion": "oficina religiosa",
        "research": "centro de investigación", "security": "empresa de seguridad",
        "surveyor": "topografía", "tax_advisor": "asesor tributario",
        "telecommunication": "telecomunicaciones", "therapist": "terapeuta",
        "translator": "traductor", "transport": "empresa de transporte de carga",
        "travel_agent": "agencia de viajes", "union": "sindicato",
        "vacant": "oficina desocupada", "visa": "trámites de visa",
        "water_utility": "empresa de agua potable", "yes": "oficina",
    },
    "place": {
        "allotments": "zona de huertos familiares", "archipelago": "archipiélago",
        "borough": "distrito urbano", "city": "ciudad", "city_block": "cuadra",
        "continent": "continente", "country": "país", "county": "condado",
        "district": "distrito", "farm": "finca", "hamlet": "caserío", "island": "isla",
        "islet": "islote", "isolated_dwelling": "vivienda aislada",
        "locality": "lugar sin población", "municipality": "municipio",
        "neighbourhood": "sector o residencial", "ocean": "océano", "plot": "lote",
        "polder": "pólder", "province": "provincia", "quarter": "barrio",
        "region": "región", "sea": "mar", "square": "plaza", "state": "departamento",
        "subdistrict": "subdistrito", "suburb": "colonia", "town": "pueblo",
        "village": "cantón",
    },
    "shop": {
        "agrarian": "agroservicio", "alcohol": "licorería", "anime": "tienda de anime",
        "antiques": "antigüedades", "appliance": "electrodomésticos",
        "art": "tienda de arte", "baby_goods": "artículos de bebé",
        "bag": "carteras y maletas", "bakery": "panadería",
        "bathroom_furnishing": "muebles de baño", "bbq": "parrillas",
        "beauty": "salón de belleza", "bed": "colchones y camas",
        "beverages": "bebidas", "bicycle": "bicicletas", "boat": "lanchas",
        "bookmaker": "casa de apuestas", "books": "librería",
        "brewing_supplies": "insumos para cervecería", "butcher": "carnicería",
        "camera": "cámaras fotográficas", "candles": "velas",
        "cannabis": "tienda de cannabis", "car": "venta de autos",
        "car_parts": "repuestos", "car_repair": "taller mecánico",
        "caravan": "casas rodantes", "carpet": "alfombras",
        "catalogue": "tienda por catálogo", "charity": "tienda de beneficencia",
        "cheese": "quesería", "chemist": "artículos de cuidado personal",
        "chocolate": "chocolatería", "clothes": "ropa", "coffee": "café en grano",
        "collector": "coleccionables", "computer": "computadoras",
        "confectionery": "dulcería", "convenience": "tienda de conveniencia",
        "copyshop": "fotocopias", "cosmetics": "cosméticos",
        "country_store": "tienda rural", "craft": "manualidades", "curtain": "cortinas",
        "dairy": "lácteos", "deli": "delicatessen",
        "department_store": "tienda por departamentos", "doityourself": "home center",
        "doors": "puertas", "dry_cleaning": "tintorería",
        "e-cigarette": "cigarrillos electrónicos",
        "electrical": "materiales eléctricos", "electronics": "artículos electrónicos",
        "erotic": "tienda erótica", "esoteric": "tienda esotérica", "fabric": "telas",
        "farm": "productos agrícolas", "fashion_accessories": "accesorios de moda",
        "fireplace": "chimeneas", "fishing": "artículos de pesca", "flooring": "pisos",
        "florist": "florería", "frame": "marcos para cuadros",
        "frozen_food": "alimentos congelados", "fuel": "venta de combustibles",
        "funeral_directors": "funeraria", "furniture": "mueblería",
        "games": "juegos de mesa", "garden_centre": "vivero", "gas": "gas propano",
        "general": "tienda general", "gift": "tienda de regalos",
        "glaziery": "vidriería", "gold_buyer": "compra de oro",
        "greengrocer": "frutas y verduras", "groundskeeping": "equipo de jardinería",
        "hairdresser": "peluquería", "hairdresser_supply": "insumos para peluquería",
        "hardware": "ferretería", "health_food": "alimentos naturales",
        "hearing_aids": "aparatos auditivos", "herbalist": "tienda naturista",
        "hifi": "equipos de sonido", "hobby": "pasatiempos", "honey": "miel",
        "household_linen": "ropa de cama y baño", "houseware": "artículos de hogar",
        "hunting": "artículos de caza",
        "interior_decoration": "decoración de interiores", "jewelry": "joyería",
        "kiosk": "kiosco", "kitchen": "muebles de cocina", "laundry": "lavandería",
        "leather": "artículos de cuero", "lighting": "iluminación",
        "locksmith": "cerrajería", "lottery": "lotería", "mall": "centro comercial",
        "massage": "masajes", "medical_supply": "equipo médico",
        "military_surplus": "artículos militares", "mobile_phone": "celulares",
        "mobile_phone_accessories": "accesorios para celulares", "model": "modelismo",
        "money_lender": "prestamista", "motorcycle": "venta de motos",
        "motorcycle_parts": "repuestos de motos",
        "motorcycle_repair": "taller de motos", "music": "tienda de discos",
        "musical_instrument": "instrumentos musicales",
        "newsagent": "puesto de periódicos",
        "nutrition_supplements": "suplementos nutricionales",
        "nuts": "nueces y semillas", "optician": "óptica",
        "outdoor": "artículos de camping", "outpost": "punto de retiro",
        "paint": "pinturas", "party": "artículos de fiesta", "pasta": "pastas",
        "pastry": "repostería", "pawnbroker": "casa de empeño",
        "perfumery": "perfumería", "pest_control": "fumigación",
        "pet": "tienda de mascotas", "pet_grooming": "peluquería canina",
        "photo": "estudio fotográfico", "piercing": "perforaciones corporales",
        "plant_hire": "alquiler de maquinaria", "pottery": "cerámica artesanal",
        "power_tools": "herramientas eléctricas", "printer_ink": "cartuchos de tinta",
        "psychic": "vidente", "pyrotechnics": "cohetería",
        "radiotechnics": "componentes electrónicos", "religion": "artículos religiosos",
        "rental": "alquiler de artículos", "repair": "taller de reparación",
        "rice": "arroz", "scuba_diving": "equipo de buceo", "seafood": "pescadería",
        "second_hand": "artículos usados", "sewing": "mercería",
        "shoe_repair": "reparación de zapatos", "shoes": "zapatería",
        "spices": "especias", "sports": "artículos deportivos",
        "stationery": "papelería", "storage_rental": "mini bodegas",
        "supermarket": "supermercado", "swimming_pool": "insumos para piscinas",
        "tailor": "sastrería", "tattoo": "estudio de tatuajes", "tea": "té",
        "telecommunication": "telecomunicaciones", "ticket": "venta de boletos",
        "tiles": "azulejos y cerámica", "tobacco": "tabaquería",
        "tool_hire": "alquiler de herramientas", "toys": "juguetería",
        "tractor": "tractores", "tractor_repair": "taller de tractores",
        "trade": "materiales de construcción", "trailer": "remolques",
        "travel_agency": "agencia de viajes", "trophy": "trofeos",
        "truck": "venta de camiones", "truck_repair": "taller de camiones",
        "tyres": "llantas", "vacant": "local vacío", "vacuum_cleaner": "aspiradoras",
        "variety_store": "tienda de variedades", "video": "videoclub",
        "video_games": "videojuegos", "watches": "relojería",
        "water": "agua purificada", "water_sports": "equipo para deportes acuáticos",
        "weapons": "armería", "wholesale": "mayoreo", "wigs": "pelucas",
        "window_blind": "persianas", "wine": "vinos", "yes": "comercio",
    },
    "sport": {
        "10pin": "boliche", "aikido": "aikido", "american_football": "fútbol americano",
        "archery": "tiro con arco", "athletics": "atletismo", "badminton": "bádminton",
        "baseball": "béisbol", "basketball": "básquetbol",
        "beachvolleyball": "voleibol de playa", "billiards": "billar", "bmx": "BMX",
        "boules": "petanca", "boxing": "boxeo", "canoe": "kayak y canotaje",
        "chess": "ajedrez", "climbing": "escalada",
        "climbing_adventure": "parque de cuerdas", "cricket": "críquet",
        "crossfit": "crossfit", "cycling": "ciclismo", "dance": "baile",
        "darts": "dardos", "equestrian": "equitación", "fencing": "esgrima",
        "fishing": "pesca deportiva", "fitness": "acondicionamiento físico",
        "free_flying": "vuelo libre (parapente)", "futsal": "futsal", "golf": "golf",
        "gymnastics": "gimnasia", "handball": "balonmano",
        "horse_racing": "carreras de caballos", "judo": "judo", "karate": "karate",
        "karting": "karting", "kickboxing": "kickboxing", "kitesurfing": "kitesurf",
        "laser_tag": "laser tag", "martial_arts": "artes marciales",
        "miniature_golf": "minigolf", "motocross": "motocross",
        "motor": "automovilismo", "multi": "multideporte",
        "obstacle_course": "carrera de obstáculos", "padel": "pádel",
        "paintball": "paintball", "parachuting": "paracaidismo", "parkour": "parkour",
        "pickleball": "pickleball", "pilates": "pilates",
        "roller_skating": "patinaje sobre ruedas", "rowing": "remo",
        "rugby_union": "rugby", "running": "carrera a pie", "sailing": "vela",
        "scuba_diving": "buceo", "shooting": "tiro deportivo", "skateboard": "patineta",
        "soccer": "fútbol", "softball": "sóftbol", "squash": "squash",
        "surfing": "surf", "swimming": "natación", "table_soccer": "futbolito de mesa",
        "table_tennis": "ping pong", "taekwondo": "taekwondo", "tennis": "tenis",
        "volleyball": "voleibol", "wakeboarding": "wakeboard",
        "water_polo": "polo acuático", "water_ski": "esquí acuático",
        "weightlifting": "levantamiento de pesas", "windsurfing": "windsurf",
        "wrestling": "lucha", "yoga": "yoga",
    },
    "tourism": {
        "alpine_hut": "refugio de montaña", "apartment": "apartamento turístico",
        "aquarium": "acuario", "artwork": "obra de arte",
        "attraction": "atracción turística",
        "bed_and_breakfast": "hospedaje con desayuno (B&B)",
        "camp_pitch": "espacio para acampar", "camp_site": "camping",
        "caravan_site": "camping para casas rodantes", "chalet": "cabaña",
        "gallery": "galería de arte", "guest_house": "casa de huéspedes",
        "hanami": "sitio para ver cerezos en flor", "hostel": "hostal",
        "hotel": "hotel", "information": "información turística",
        "love_hotel": "autohotel", "motel": "motel", "museum": "museo",
        "picnic_site": "área de picnic", "resort": "complejo turístico (resort)",
        "spa_resort": "spa / centro termal", "theme_park": "parque de diversiones",
        "trail_riding_station": "estación ecuestre", "viewpoint": "mirador",
        "wilderness_hut": "refugio rústico", "wine_cellar": "cava de vinos",
        "yes": "sitio turístico", "zoo": "zoológico",
    },
}


# ------------------------------------------------------------- OVERPASS ---
def consultar(consulta, etiqueta, modo="obligatorio"):
    """Envia una consulta a Overpass.

    modo="obligatorio"    -> insiste y aborta el programa si no lo logra.
    modo="puede_partirse" -> si el servidor dice que la consulta es demasiado
                             grande devuelve None enseguida, porque la solucion
                             no es reintentar sino partir el area en pedazos.
    modo="ultimo_recurso" -> ya no hay como partir mas: insiste igual que en
                             obligatorio, pero devuelve None en vez de abortar.
    """
    for intento in range(4):
        servidor = SERVIDORES[intento % len(SERVIDORES)]
        demasiado_grande = False
        try:
            r = requests.post(servidor, data={"data": consulta}, timeout=1200,
                              headers={"User-Agent": "empresas-sv/2.0"})
            if r.status_code == 200:
                datos = r.json()
                nota = datos.get("remark", "")
                if "error" in nota.lower():
                    print("   el servidor no pudo con la consulta: %s" % nota.strip())
                    demasiado_grande = True
                else:
                    return datos
            else:
                print("   %s respondio %d" % (servidor, r.status_code))
                demasiado_grande = r.status_code in (400, 504)
        except Exception as exc:
            print("   %s fallo: %s" % (servidor, exc))

        if demasiado_grande and modo == "puede_partirse":
            return None
        if modo == "puede_partirse" and intento >= 1:
            return None
        if intento == 3:
            break
        espera = 10 * (2 ** intento)
        print("   reintentando %s en %d s..." % (etiqueta, espera))
        time.sleep(espera)

    if modo == "obligatorio":
        raise SystemExit("Overpass no respondio (%s). Intenta de nuevo mas tarde." % etiqueta)
    return None


def preambulo(ids=None):
    """Define el area de busqueda: los departamentos, o unas relaciones sueltas."""
    if ids:
        seleccion = "rel(id:%s)" % ",".join(str(i) for i in ids)
    else:
        seleccion = ('rel(%s)["boundary"="administrative"]["admin_level"!="2"]'
                     '["name"~"^(%s)$"]' % (BBOX_PAIS, "|".join(DEPARTAMENTOS)))
    return "%s->.dep;\n.dep map_to_area ->.zona;" % seleccion


def filtros_de(clave):
    """Filtros Overpass de un grupo."""
    if clave == "building" and not EDIFICIOS_COMPLETOS:
        return ['nwr["building"]["name"]',
                'nwr["building"~"^(commercial|retail|industrial|warehouse|office|'
                'hotel|school|university|hospital|church|cathedral|chapel|mosque|'
                'temple|government|civic|public|train_station|stadium|sports_hall|'
                'supermarket|kiosk|construction|farm|barn|greenhouse|hangar)$"]']
    return ['nwr["%s"]' % clave]


def consulta_de_grupo(clave, ids=None):
    cuerpo = "\n".join("  %s(area.zona);" % f for f in filtros_de(clave))
    return ("[out:json][timeout:%d];\n%s\n(\n%s\n);\nout tags center;"
            % (TIMEOUT_CONSULTA, preambulo(ids), cuerpo))


# -------------------------------------------------------------- LIMITES ---
def descargar_limites():
    """Baja los limites de los departamentos y de todo lo que hay dentro."""
    cache = os.path.join(CARPETA, "_limites.json")
    if os.path.exists(cache):
        print("Limites administrativos: usando la copia guardada.")
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    print("Descargando los limites de %s..." % " y ".join(DEPARTAMENTOS))
    consulta = ('[out:json][timeout:%d];\n%s\n(\n  .dep;\n'
                '  rel(area.zona)["boundary"="administrative"]["admin_level"~"%s"];\n'
                ');\nout geom;' % (TIMEOUT_CONSULTA, preambulo(), NIVELES_INTERNOS))
    datos = consultar(consulta, "limites")
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)
    return datos


def nivel_de(tags):
    try:
        return int(tags.get("admin_level", 99))
    except (TypeError, ValueError):
        return 99


def armar_limites(datos):
    """Convierte cada limite en segmentos agrupados por bandas de latitud.

    Descarta los limites de departamentos vecinos que Overpass arrastra por
    tocar la frontera: se quedan solo los que tienen su centro dentro de los
    departamentos pedidos. Devuelve la lista ordenada de lo general a lo
    particular: departamento, luego municipio, luego distrito.
    """
    poligonos, vistos = [], set()
    for relacion in datos.get("elements", []):
        tags = relacion.get("tags", {})
        nombre = tags.get("name", "")
        identificador = relacion.get("id")
        # Se deduplica por id, no por nombre: dos distritos distintos pueden
        # llamarse igual y perder uno dejaria un hueco sin consultar.
        if not nombre or identificador in vistos:
            continue
        vistos.add(identificador)

        rejilla = collections.defaultdict(list)
        suma_lat = suma_lon = puntos_total = 0
        for miembro in relacion.get("members", []):
            if miembro.get("role") == "label":
                continue
            puntos = miembro.get("geometry") or []
            for punto in puntos:
                suma_lat += punto["lat"]
                suma_lon += punto["lon"]
                puntos_total += 1
            for a, b in zip(puntos, puntos[1:]):
                if a["lat"] == b["lat"]:
                    continue   # los segmentos horizontales no cruzan el rayo
                segmento = (a["lat"], a["lon"], b["lat"], b["lon"])
                desde = int(min(a["lat"], b["lat"]) / PASO_REJILLA)
                hasta = int(max(a["lat"], b["lat"]) / PASO_REJILLA)
                for banda in range(desde, hasta + 1):
                    rejilla[banda].append(segmento)
        if not rejilla or not puntos_total:
            continue
        poligonos.append({"nivel": nivel_de(tags), "nombre": nombre,
                          "id": identificador, "rejilla": dict(rejilla),
                          "centro": (suma_lat / puntos_total, suma_lon / puntos_total)})

    departamentos = [p for p in poligonos if p["nivel"] <= 4]
    internos, ajenos = [], 0
    for poligono in poligonos:
        if poligono in departamentos:
            continue
        lat, lon = poligono["centro"]
        if any(contiene(lat, lon, d["rejilla"]) for d in departamentos):
            internos.append(poligono)
        else:
            ajenos += 1
    if ajenos:
        print("  (se descartaron %d limites de departamentos vecinos)" % ajenos)

    limites = departamentos + internos
    limites.sort(key=lambda l: (l["nivel"], l["nombre"]))
    return limites


def contiene(lat, lon, rejilla):
    """Punto en poligono por conteo de cruces, solo con la banda que toca."""
    cruces = 0
    for lat1, lon1, lat2, lon2 in rejilla.get(int(lat / PASO_REJILLA), ()):
        if (lat1 > lat) != (lat2 > lat):
            corte = lon1 + (lat - lat1) * (lon2 - lon1) / (lat2 - lat1)
            if lon < corte:
                cruces += 1
    return cruces % 2 == 1


def ubicacion(lat, lon, limites):
    """Devuelve (departamento, municipio, distrito) del punto."""
    dentro = [(l["nivel"], l["nombre"]) for l in limites
              if contiene(lat, lon, l["rejilla"])]
    if not dentro:
        return "", "", ""
    departamento = next((n for niv, n in dentro if niv <= 4), "")
    internos = [n for niv, n in dentro if niv > 4]
    if not internos:
        return departamento, "", ""
    distrito = internos[-1]
    municipio = internos[-2] if len(internos) >= 2 else distrito
    return departamento, municipio, distrito


def particiones(limites):
    """Formas de partir el area, de la mas gruesa a la mas fina.

    Cada particion es una lista de (nombre, [ids de relacion]) para consultar
    por separado. La primera es el area completa en una sola consulta.
    """
    trozos = [[("todo el territorio", None)]]
    niveles = sorted({l["nivel"] for l in limites if l["nivel"] > 4})
    for nivel in niveles:
        unidades = [(l["nombre"], [l["id"]]) for l in limites
                    if l["nivel"] == nivel and l["id"]]
        if unidades:
            trozos.append(unidades)
    return trozos


# -------------------------------------------------------------- DESCARGA ---
def descargar_grupo(grupo, clave, trozos, limites):
    """Descarga un grupo, partiendo el area si el servidor no puede con ella.

    Devuelve (filas, zonas_fallidas). Cada respuesta se convierte a filas en
    el momento, para no tener en memoria los elementos crudos de un grupo
    entero. En la particion mas fina ya no hay donde replegarse: si una zona
    falla se sigue con las demas y se reporta, en vez de tirar la descarga.
    """
    primera = len(trozos) - 1 if grupo in GRUPOS_PESADOS else 0
    for indice in range(primera, len(trozos)):
        particion = trozos[indice]
        ultima = (indice == len(trozos) - 1)
        if len(particion) > 1:
            print("  consultando %d zonas por separado..." % len(particion))

        filas, fallidas, replegarse = {}, [], False
        for numero, (nombre, ids) in enumerate(particion, 1):
            datos = consultar(consulta_de_grupo(clave, ids),
                              "%s / %s" % (grupo, nombre),
                              "ultimo_recurso" if ultima else "puede_partirse")
            if datos is None:
                if not ultima:
                    print("  no se pudo con '%s'; probando una division mas fina"
                          % nombre)
                    replegarse = True
                    break
                print("  AVISO: '%s' no se pudo descargar; queda incompleto" % nombre)
                fallidas.append(nombre)
                continue
            for elemento in datos.get("elements", []):
                registro = fila(elemento, grupo, clave, limites)
                if registro:
                    filas[(registro["osm_tipo"], registro["osm_id"])] = registro
            if len(particion) > 1:
                print("    %3d/%d %-28s %7d acumulados"
                      % (numero, len(particion), nombre[:28], len(filas)))
                time.sleep(2)
        if not replegarse:
            return list(filas.values()), fallidas
    return [], ["todo el grupo"]


# -------------------------------------------------------------- SALIDA ---
def traducir(clave, crudo):
    """Traduce un valor de OSM al español.

    OSM admite varios valores separados por ';' (cuisine=pizza;burger), asi
    que se traduce cada uno. Lo que no este en la tabla se omite: el valor
    original siempre queda en la columna 'valor'.
    """
    tabla = ETIQUETAS.get(clave)
    if not tabla or not crudo:
        return ""
    traducidos = [tabla.get(parte.strip(), "") for parte in crudo.split(";")]
    return "; ".join(t for t in traducidos if t)


def valor(tags, *llaves):
    for llave in llaves:
        if tags.get(llave):
            return tags[llave]
    return ""


def fila(elemento, grupo, clave, limites):
    tags = elemento.get("tags", {})
    centro = elemento.get("center", {})
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None

    crudo = tags.get(clave, "")
    calle = valor(tags, "addr:street", "addr:place")
    numero = tags.get("addr:housenumber", "")
    departamento, municipio, distrito = ubicacion(lat, lon, limites)
    return {
        "grupo": grupo,
        "clave": clave,
        "valor": crudo,
        "etiqueta_es": traducir(clave, crudo),
        "nombre": valor(tags, "name", "name:es", "brand", "operator"),
        "marca": valor(tags, "brand", "brand:wikidata"),
        "operador": tags.get("operator", ""),
        "departamento": departamento,
        "municipio": municipio,
        "distrito": distrito,
        "latitud": lat,
        "longitud": lon,
        "direccion": ("%s %s" % (calle, numero)).strip(),
        "ciudad": valor(tags, "addr:city", "addr:municipality"),
        "telefono": valor(tags, "phone", "contact:phone", "contact:mobile"),
        "correo": valor(tags, "email", "contact:email"),
        "sitio_web": valor(tags, "website", "contact:website", "contact:facebook"),
        "horario": tags.get("opening_hours", ""),
        "cocina": tags.get("cuisine", ""),
        "cocina_es": traducir("cuisine", tags.get("cuisine", "")),
        "deporte": tags.get("sport", ""),
        "deporte_es": traducir("sport", tags.get("sport", "")),
        "tipo_club": tags.get("club", ""),
        "tipo_club_es": traducir("club", tags.get("club", "")),
        "osm_tipo": elemento["type"],
        "osm_id": elemento["id"],
        "url_osm": "https://www.openstreetmap.org/%s/%s" % (elemento["type"], elemento["id"]),
    }


def guardar_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def main():
    os.makedirs(CARPETA, exist_ok=True)

    limites = armar_limites(descargar_limites())
    por_nivel = collections.defaultdict(list)
    for l in limites:
        por_nivel[l["nivel"]].append(l["nombre"])
    for nivel in sorted(por_nivel):
        nombres = sorted(por_nivel[nivel])
        muestra = ", ".join(nombres[:5]) + (", ..." if len(nombres) > 5 else "")
        print("  nivel %-2d  %3d limites   %s" % (nivel, len(nombres), muestra))

    encontrados = [l["nombre"] for l in limites if l["nivel"] <= 4]
    for esperado in DEPARTAMENTOS:
        if esperado not in encontrados:
            print("  OJO: no se encontro el limite del departamento de %s. "
                  "La busqueda puede quedar incompleta." % esperado)
    if not [l for l in limites if l["nivel"] > 4]:
        print("  OJO: no se encontro ningun municipio ni distrito; las columnas "
              "municipio y distrito iran vacias.")
    trozos = particiones(limites)
    print()

    todas, incompletos = {}, {}
    for grupo, clave in GRUPOS:
        print("Descargando %s (%s=*)..." % (grupo, clave))
        filas, fallidas = descargar_grupo(grupo, clave, trozos, limites)
        if fallidas:
            incompletos[grupo] = fallidas
        filas.sort(key=lambda f: (f["municipio"], f["distrito"], f["valor"],
                                  f["nombre"] == "", f["nombre"].lower()))

        ruta = os.path.join(CARPETA, "osm_%s.csv" % grupo)
        guardar_csv(ruta, filas)
        print("  %d registros (%d con nombre)  ->  %s"
              % (len(filas), sum(1 for f in filas if f["nombre"]), ruta))

        for f in filas:
            llave = (f["osm_tipo"], f["osm_id"])
            if llave in todas:
                todas[llave]["grupo"] += "|" + f["grupo"]
                todas[llave]["clave"] += "|" + f["clave"]
                todas[llave]["valor"] += "|" + f["valor"]
                if f["etiqueta_es"]:
                    previa = todas[llave]["etiqueta_es"]
                    todas[llave]["etiqueta_es"] = (previa + "|" if previa else "") + f["etiqueta_es"]
            else:
                todas[llave] = dict(f)
        time.sleep(3)   # pausa amable con el servidor publico

    filas = sorted(todas.values(),
                   key=lambda f: (f["municipio"], f["distrito"], f["grupo"],
                                  f["nombre"].lower()))
    guardar_csv(os.path.join(CARPETA, "osm_todo.csv"), filas)

    print("\nTotal sin duplicados: %d registros" % len(filas))
    por_distrito = collections.Counter(f["distrito"] or "(sin distrito)" for f in filas)
    for nombre, cuantos in sorted(por_distrito.items()):
        print("  %-28s %6d" % (nombre, cuantos))

    if incompletos:
        print("\nZonas que el servidor no pudo entregar (datos incompletos ahi):")
        for grupo, zonas in sorted(incompletos.items()):
            print("  %-18s %s" % (grupo, ", ".join(zonas)))
        print("  Vuelve a correr el script mas tarde para completarlas.")

    print("\n  %s/osm_todo.csv" % CARPETA)
    if len(filas) <= LIMITE_GEOJSON:
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [f["longitud"], f["latitud"]]},
             "properties": f}
            for f in filas]}
        with open(os.path.join(CARPETA, "osm_todo.geojson"), "w", encoding="utf-8") as fh:
            json.dump(geojson, fh, ensure_ascii=False)
        print("  %s/osm_todo.geojson" % CARPETA)
    else:
        print("  (GeoJSON omitido: %d registros superan el limite de %d; "
              "usa los CSV)" % (len(filas), LIMITE_GEOJSON))
    print("\nDatos (c) colaboradores de OpenStreetMap, licencia ODbL.")


if __name__ == "__main__":
    main()
