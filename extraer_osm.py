#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extraer_osm.py
==============

Extractor de datos de OpenStreetMap (via Overpass API) para los departamentos
de SAN SALVADOR y LA LIBERTAD (El Salvador), con salida en archivos Excel
(uno por categoria).

Que hace
--------
1. Resuelve en OSM los limites administrativos de El Salvador -> departamentos
   solicitados -> municipios y distritos (cualquier admin_level 5..9).
2. Consulta Overpass por cada categoria (shop, office, craft, amenity, leisure,
   tourism, healthcare, building, landuse, place, natural, historic, man_made,
   public_transport, aeroway, emergency, industrial, brand, sport, cuisine,
   club) dentro del area de cada departamento. Las categorias "pesadas"
   (building, landuse, place, natural, ...) se dividen automaticamente en
   mosaicos (quadtree) para no exceder el timeout del servidor.
3. A cada elemento le asigna departamento / municipio / distrito por
   point-in-polygon usando las geometrias administrativas descargadas.
4. Escribe un Excel por categoria en el directorio de salida con las columnas:
   categoria, categoria_es, subcategoria, subcategoria_es, nombre, marca,
   operador, latitud, longitud, departamento, municipio, distrito, direccion,
   telefono, correo, sitio_web, horario, ... y `todas_las_etiquetas` (JSON con
   absolutamente todas las etiquetas OSM del elemento).

Uso rapido
----------
    pip install -r requirements.txt
    python extraer_osm.py                         # todo (tarda horas)
    python extraer_osm.py --categorias shop office craft amenity
    python extraer_osm.py --departamentos "San Salvador"
    python extraer_osm.py --listar-categorias
    python extraer_osm.py --formato ambos --salida ./salida

Notas de operacion
------------------
* Las respuestas de Overpass se guardan en cache (./cache_osm) para que re-correr
  el script no vuelva a golpear el servidor. Use --sin-cache para ignorarla.
* Overpass es un servicio comunitario y gratuito: el script hace las consultas
  una por una, con pausa configurable (--pausa) y reintentos con espera
  exponencial ante 429/504.
* shapely es opcional: si no esta instalada se usa un algoritmo interno de
  point-in-polygon (mas lento pero equivalente).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Configuracion general
# --------------------------------------------------------------------------- #

VERSION = "1.0.0"

#: Servidores Overpass (se usan en orden; si uno falla se prueba el siguiente).
ENDPOINTS_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

#: Departamentos a extraer (nombre tal como esta en OSM, admin_level=4).
DEPARTAMENTOS_OBJETIVO = ["San Salvador", "La Libertad"]

#: Codigo ISO del pais, para anclar la busqueda de los departamentos.
PAIS_ISO = "SV"
PAIS_NOMBRE = "El Salvador"
#: bbox de respaldo (sur, oeste, norte, este) si falla la base de areas.
PAIS_BBOX = (13.0, -90.2, 14.5, -87.6)

USER_AGENT = (
    "extraer_osm/%s (extraccion academica de POIs de San Salvador y La Libertad; "
    "contacto: usuario de OpenStreetMap)" % VERSION
)

DIR_SALIDA_DEF = "salida"
DIR_CACHE_DEF = "cache_osm"

#: Maximo de filas por hoja de Excel (limite real de xlsx = 1,048,576).
MAX_FILAS_HOJA = 1_000_000

# --------------------------------------------------------------------------- #
# Taxonomia: categorias -> subcategorias (valor OSM -> nombre en espanol)
# --------------------------------------------------------------------------- #
# IMPORTANTE: el script consulta TODOS los valores de cada llave (por ejemplo
# `shop=*`), no solo los listados aqui. Estos diccionarios solo sirven para
# traducir la subcategoria al espanol; cualquier valor no listado se exporta
# igual, con su valor OSM crudo en `subcategoria` y una traduccion automatica
# legible en `subcategoria_es`.

VALORES_SHOP = {
    # --- alimentos y bebidas ---
    "supermarket": "Supermercado",
    "convenience": "Tienda de conveniencia",
    "grocery": "Abarroteria",
    "general": "Tienda general",
    "variety_store": "Tienda de variedades",
    "wholesale": "Mayorista / distribuidora",
    "kiosk": "Kiosco",
    "mall": "Centro comercial",
    "department_store": "Tienda por departamentos",
    "bakery": "Panaderia",
    "pastry": "Pasteleria",
    "confectionery": "Dulceria",
    "chocolate": "Chocolateria",
    "butcher": "Carniceria",
    "seafood": "Pescaderia / marisqueria",
    "cheese": "Queseria",
    "dairy": "Lacteos",
    "deli": "Delicatessen",
    "greengrocer": "Frutas y verduras",
    "farm": "Venta de productos agricolas",
    "tortilla": "Tortilleria",
    "ice_cream": "Heladeria",
    "alcohol": "Venta de licores",
    "wine": "Vinateria",
    "beverages": "Bebidas",
    "water": "Venta de agua purificada",
    "coffee": "Venta de cafe",
    "tea": "Venta de te",
    "spices": "Especias",
    "health_food": "Alimentos saludables",
    "nutrition_supplements": "Suplementos nutricionales",
    "frozen_food": "Alimentos congelados",
    "food": "Alimentos",
    "brewing": "Insumos de cerveceria",
    "honey": "Venta de miel",
    "farm_supply": "Insumos agricolas",
    # --- ropa, calzado y accesorios ---
    "clothes": "Ropa",
    "boutique": "Boutique",
    "fashion": "Moda",
    "fashion_accessories": "Accesorios de moda",
    "shoes": "Zapateria",
    "shoe_repair": "Reparacion de calzado",
    "bag": "Bolsos y maletas",
    "jewelry": "Joyeria",
    "watches": "Relojeria",
    "fabric": "Telas",
    "sewing": "Merceria / costura",
    "haberdashery": "Merceria",
    "leather": "Articulos de cuero",
    "tailor": "Sastreria",
    "clothes_alteration": "Arreglo de ropa",
    "second_hand": "Articulos de segunda mano",
    "charity": "Tienda de beneficencia",
    "baby_goods": "Articulos para bebe",
    "household_linen": "Blancos y ropa de cama",
    "uniform": "Uniformes",
    "wedding": "Articulos de boda",
    "costume": "Disfraces",
    # --- salud y belleza ---
    "chemist": "Farmacia / drogueria (chemist)",
    "pharmacy": "Farmacia",
    "cosmetics": "Cosmeticos",
    "perfumery": "Perfumeria",
    "hairdresser": "Salon de belleza / barberia",
    "hairdresser_supply": "Insumos de belleza",
    "beauty": "Estetica / spa",
    "nail_salon": "Salon de unas",
    "massage": "Masajes",
    "tattoo": "Estudio de tatuajes",
    "piercing": "Perforaciones",
    "optician": "Optica",
    "hearing_aids": "Aparatos auditivos",
    "medical_supply": "Insumos medicos",
    "herbalist": "Herbolaria / productos naturales",
    "erotic": "Tienda para adultos",
    # --- ferreteria, construccion y hogar ---
    "hardware": "Ferreteria",
    "doityourself": "Ferreteria y materiales de construccion",
    "trade": "Materiales de construccion (venta al mayoreo)",
    "building_materials": "Materiales de construccion",
    "paint": "Pinturas",
    "tiles": "Pisos y azulejos",
    "flooring": "Pisos",
    "glaziery": "Vidrieria",
    "doors": "Puertas",
    "windows": "Ventanas",
    "window_blind": "Persianas y cortinas",
    "curtain": "Cortinas",
    "bathroom_furnishing": "Muebles de bano",
    "kitchen": "Cocinas y muebles de cocina",
    "fireplace": "Chimeneas",
    "furniture": "Muebleria",
    "garden_furniture": "Muebles de jardin",
    "interior_decoration": "Decoracion de interiores",
    "carpet": "Alfombras",
    "bed": "Colchones y camas",
    "houseware": "Articulos para el hogar",
    "kitchenware": "Articulos de cocina",
    "lighting": "Iluminacion",
    "electrical": "Materiales electricos",
    "plumbing": "Materiales de fontaneria",
    "hvac": "Aire acondicionado y climatizacion",
    "solar": "Energia solar",
    "energy": "Energia / paneles solares",
    "swimming_pool": "Piscinas y accesorios",
    "pottery": "Ceramica",
    "candles": "Velas",
    "cleaning_supplies": "Productos de limpieza",
    # --- tecnologia y electronica ---
    "electronics": "Electrodomesticos y electronica",
    "appliance": "Electrodomesticos",
    "hifi": "Audio y sonido",
    "mobile_phone": "Celulares y telefonia",
    "computer": "Computadoras",
    "video_games": "Videojuegos",
    "camera": "Camaras y fotografia",
    "photo": "Fotografia",
    "radiotechnics": "Componentes electronicos",
    "printer_ink": "Tintas y toner",
    "telecommunication": "Telecomunicaciones",
    "electronics_repair": "Reparacion de electronicos",
    "security": "Seguridad y vigilancia",
    # --- vehiculos ---
    "car": "Venta de autos",
    "car_repair": "Taller automotriz",
    "car_parts": "Repuestos automotrices",
    "tyres": "Llantas",
    "car_accessories": "Accesorios para autos",
    "motorcycle": "Venta de motocicletas",
    "motorcycle_repair": "Taller de motocicletas",
    "motorcycle_parts": "Repuestos de motocicletas",
    "bicycle": "Bicicleteria",
    "truck": "Venta de camiones",
    "truck_repair": "Taller de camiones",
    "trailer": "Remolques",
    "caravan": "Casas rodantes",
    "boat": "Venta de lanchas y botes",
    "atv": "Cuadrimotos",
    "machinery": "Maquinaria",
    "tools": "Herramientas",
    "agrarian": "Agroservicio",
    "tractor": "Tractores y maquinaria agricola",
    "fuel": "Venta de combustible envasado",
    "gas": "Venta de gas propano",
    "lubricants": "Lubricantes",
    # --- agro, jardin y mascotas ---
    "garden_centre": "Vivero / centro de jardineria",
    "florist": "Floristeria",
    "pet": "Tienda de mascotas",
    "pet_grooming": "Estetica canina",
    "pet_supply": "Insumos para mascotas",
    # --- papeleria, cultura y ocio ---
    "books": "Libreria",
    "stationery": "Papeleria",
    "newsagent": "Venta de periodicos y revistas",
    "copyshop": "Fotocopias e impresion",
    "art": "Galeria / articulos de arte",
    "frame": "Marcos y enmarcado",
    "craft": "Manualidades",
    "hobby": "Pasatiempos",
    "musical_instrument": "Instrumentos musicales",
    "music": "Musica (discos)",
    "video": "Videos y peliculas",
    "games": "Juegos",
    "toys": "Jugueteria",
    "party": "Articulos para fiestas",
    "gift": "Regalos y souvenirs",
    "souvenir": "Souvenirs",
    "antiques": "Antiguedades",
    "collector": "Coleccionismo",
    "auction_house": "Casa de subastas",
    "religion": "Articulos religiosos",
    "sports": "Articulos deportivos",
    "outdoor": "Articulos para aire libre",
    "fishing": "Articulos de pesca",
    "hunting": "Articulos de caza",
    "scuba_diving": "Articulos de buceo",
    "surf": "Articulos de surf",
    "weapons": "Armeria",
    "military_surplus": "Articulos militares",
    "e-cigarette": "Cigarrillos electronicos",
    "tobacco": "Tabaqueria",
    "cannabis": "Cannabis",
    "lottery": "Loteria",
    "bookmaker": "Casa de apuestas",
    # --- servicios comerciales ---
    "laundry": "Lavanderia",
    "dry_cleaning": "Tintoreria",
    "ironing": "Planchado",
    "pawnbroker": "Casa de empeno",
    "money_lender": "Prestamista",
    "money_transfer": "Envio de remesas",
    "insurance": "Seguros",
    "estate_agent": "Inmobiliaria",
    "travel_agency": "Agencia de viajes",
    "ticket": "Venta de boletos",
    "locksmith": "Cerrajeria",
    "funeral_directors": "Funeraria",
    "storage_rental": "Alquiler de bodegas",
    "rental": "Alquiler de articulos",
    "tool_hire": "Alquiler de herramientas",
    "car_rental": "Alquiler de autos",
    "printing": "Imprenta",
    "sign_making": "Rotulacion",
    "coworking": "Espacio de coworking",
    "internet_cafe": "Cibercafe",
    "vacant": "Local comercial vacio",
    "yes": "Comercio (sin especificar)",
}

VALORES_OFFICE = {
    "company": "Empresa",
    "corporate": "Corporativo",
    "government": "Oficina de gobierno",
    "administrative": "Oficina administrativa",
    "quango": "Entidad autonoma / parestatal",
    "diplomatic": "Embajada / consulado",
    "lawyer": "Bufete de abogados",
    "notary": "Notaria",
    "accountant": "Contadores",
    "tax_advisor": "Asesoria fiscal",
    "financial": "Servicios financieros",
    "financial_advisor": "Asesoria financiera",
    "bank": "Oficina bancaria",
    "insurance": "Aseguradora",
    "estate_agent": "Inmobiliaria",
    "property_management": "Administracion de propiedades",
    "it": "Empresa de tecnologia (TI)",
    "telecommunication": "Telecomunicaciones",
    "web_design": "Diseno web",
    "employment_agency": "Agencia de empleo",
    "recruitment_agency": "Agencia de reclutamiento",
    "architect": "Arquitectos",
    "engineer": "Ingenieria",
    "surveyor": "Topografia",
    "consulting": "Consultoria",
    "advertising_agency": "Agencia de publicidad",
    "graphic_design": "Diseno grafico",
    "marketing": "Mercadeo",
    "newspaper": "Periodico",
    "publisher": "Editorial",
    "ngo": "ONG",
    "association": "Asociacion",
    "foundation": "Fundacion",
    "charity": "Organizacion de beneficencia",
    "political_party": "Partido politico",
    "union": "Sindicato",
    "logistics": "Logistica",
    "courier": "Courier / mensajeria",
    "moving_company": "Empresa de mudanzas",
    "construction_company": "Constructora",
    "coworking": "Coworking",
    "research": "Investigacion",
    "educational_institution": "Institucion educativa",
    "travel_agent": "Agencia de viajes",
    "guide": "Guia turistico",
    "religion": "Oficina religiosa",
    "security": "Empresa de seguridad",
    "private_investigator": "Investigador privado",
    "translator": "Traductor",
    "therapist": "Terapeuta",
    "adoption_agency": "Agencia de adopciones",
    "water_utility": "Empresa de agua",
    "energy_supplier": "Distribuidora de energia",
    "forestry": "Forestal",
    "visa": "Tramite de visas",
    "tax": "Oficina de impuestos",
    "register": "Registro",
    "insurance_agency": "Agencia de seguros",
    "yes": "Oficina (sin especificar)",
}

VALORES_CRAFT = {
    "carpenter": "Carpinteria",
    "joiner": "Ebanisteria",
    "cabinet_maker": "Fabricacion de muebles",
    "electrician": "Electricista",
    "plumber": "Fontaneria / plomeria",
    "gasfitter": "Instalacion de gas",
    "hvac": "Aire acondicionado y refrigeracion",
    "blacksmith": "Herreria",
    "metal_construction": "Estructuras metalicas / soldadura",
    "welder": "Soldadura",
    "tinsmith": "Hojalateria",
    "locksmith": "Cerrajeria",
    "glaziery": "Vidrieria",
    "painter": "Pintor",
    "plasterer": "Enyesado",
    "roofer": "Techos",
    "tiler": "Colocacion de azulejos",
    "stonemason": "Canteria",
    "bricklayer": "Albanileria",
    "builder": "Constructor",
    "scaffolder": "Andamios",
    "insulation": "Aislamiento",
    "floorer": "Instalacion de pisos",
    "parquet_layer": "Instalacion de parquet",
    "window_construction": "Fabricacion de ventanas",
    "door_construction": "Fabricacion de puertas",
    "sun_protection": "Toldos y proteccion solar",
    "tailor": "Sastreria",
    "dressmaker": "Costurera / modista",
    "shoemaker": "Zapatero",
    "saddler": "Talabarteria",
    "upholsterer": "Tapiceria",
    "photographer": "Fotografo",
    "photographic_laboratory": "Laboratorio fotografico",
    "jeweller": "Joyero",
    "goldsmith": "Orfebre",
    "watchmaker": "Relojero",
    "signmaker": "Rotulacion",
    "printer": "Imprenta",
    "bookbinder": "Encuadernacion",
    "brewery": "Cerveceria artesanal",
    "distillery": "Destileria",
    "winery": "Vinicola",
    "pottery": "Alfareria / ceramica",
    "basket_maker": "Cesteria",
    "caterer": "Servicio de banquetes",
    "confectionery": "Reposteria artesanal",
    "bakery": "Panaderia artesanal",
    "gardener": "Jardineria",
    "agricultural_engines": "Maquinaria agricola",
    "beekeeper": "Apicultura",
    "handicraft": "Artesania",
    "sculptor": "Escultor",
    "artist": "Artista",
    "musical_instrument": "Fabricacion de instrumentos musicales",
    "piano_tuner": "Afinador de pianos",
    "sawmill": "Aserradero",
    "boatbuilder": "Constructor de embarcaciones",
    "turner": "Tornero",
    "key_cutter": "Duplicado de llaves",
    "electronics_repair": "Reparacion de electronicos",
    "computer_repair": "Reparacion de computadoras",
    "mobile_phone_repair": "Reparacion de celulares",
    "car_repair": "Taller automotriz (artesanal)",
    "optician": "Optica (taller)",
    "orthopedic_technician": "Tecnico ortopedico",
    "dental_technician": "Laboratorio dental",
    "oil_mill": "Molino de aceite",
    "grinding_mill": "Molino",
    "chimney_sweeper": "Limpieza de chimeneas",
    "cleaning": "Servicio de limpieza",
    "rigger": "Aparejador",
    "well_driller": "Perforacion de pozos",
    "yes": "Taller / oficio (sin especificar)",
}

VALORES_INDUSTRIAL = {
    "factory": "Fabrica",
    "warehouse": "Bodega",
    "refinery": "Refineria",
    "sawmill": "Aserradero",
    "slaughterhouse": "Rastro / matadero",
    "shipyard": "Astillero",
    "depot": "Deposito",
    "distributor": "Distribuidora",
    "logistics": "Logistica",
    "oil": "Industria petrolera",
    "gas": "Industria de gas",
    "mine": "Mina",
    "quarry": "Cantera",
    "port": "Puerto industrial",
    "brewery": "Cerveceria industrial",
    "bakery": "Panificadora industrial",
    "brickyard": "Ladrillera",
    "foundry": "Fundicion",
    "machine_shop": "Taller de maquinado",
    "scrap_yard": "Chatarreria",
    "ice_factory": "Fabrica de hielo",
    "grinding_mill": "Molino industrial",
    "wellsite": "Pozo industrial",
    "water_treatment": "Planta de tratamiento de agua",
    "salt_pond": "Salinera",
    "yes": "Industria (sin especificar)",
}

VALORES_AMENITY = {
    # --- comida y bebida ---
    "restaurant": "Restaurante",
    "cafe": "Cafeteria",
    "fast_food": "Comida rapida",
    "food_court": "Plaza de comidas",
    "bar": "Bar",
    "pub": "Pub / cerveceria",
    "biergarten": "Jardin cervecero",
    "ice_cream": "Heladeria",
    "bbq": "Area de parrillas",
    "juice_bar": "Bar de jugos",
    "internet_cafe": "Cibercafe",
    "hookah_lounge": "Salon de narguile",
    # --- finanzas ---
    "bank": "Banco",
    "atm": "Cajero automatico",
    "bureau_de_change": "Casa de cambio",
    "money_transfer": "Remesas / envio de dinero",
    "payment_centre": "Centro de pagos / colecturia",
    "payment_terminal": "Terminal de pago",
    "mobile_money_agent": "Agente de dinero movil",
    # --- salud ---
    "hospital": "Hospital",
    "clinic": "Clinica",
    "doctors": "Consultorio medico",
    "dentist": "Clinica dental",
    "pharmacy": "Farmacia",
    "veterinary": "Veterinaria",
    "nursing_home": "Hogar de ancianos",
    "social_facility": "Instalacion de asistencia social",
    "childcare": "Guarderia",
    "blood_donation": "Donacion de sangre",
    "first_aid": "Primeros auxilios",
    # --- educacion ---
    "kindergarten": "Kinder / parvularia",
    "school": "Escuela / centro escolar",
    "college": "Instituto tecnologico",
    "university": "Universidad",
    "language_school": "Academia de idiomas",
    "driving_school": "Escuela de manejo",
    "music_school": "Escuela de musica",
    "dancing_school": "Escuela de danza",
    "prep_school": "Academia de refuerzo",
    "training": "Centro de capacitacion",
    "research_institute": "Instituto de investigacion",
    "library": "Biblioteca",
    "public_bookcase": "Biblioteca publica de estante",
    "archive": "Archivo",
    "toy_library": "Ludoteca",
    # --- transporte ---
    "fuel": "Gasolinera",
    "charging_station": "Estacion de carga electrica",
    "parking": "Estacionamiento",
    "parking_space": "Plaza de estacionamiento",
    "parking_entrance": "Entrada de estacionamiento",
    "motorcycle_parking": "Estacionamiento de motos",
    "bicycle_parking": "Estacionamiento de bicicletas",
    "bicycle_rental": "Alquiler de bicicletas",
    "bicycle_repair_station": "Estacion de reparacion de bicicletas",
    "car_wash": "Lavado de autos",
    "car_rental": "Alquiler de autos",
    "car_sharing": "Autos compartidos",
    "car_pooling": "Punto de viaje compartido",
    "vehicle_inspection": "Revision vehicular",
    "driving_range": "Campo de practica",
    "taxi": "Parada de taxis",
    "bus_station": "Terminal de buses",
    "ferry_terminal": "Terminal de ferry",
    "boat_rental": "Alquiler de lanchas",
    "boat_storage": "Guarda de embarcaciones",
    "weighbridge": "Bascula",
    "compressed_air": "Aire comprimido",
    "fuel_station": "Estacion de combustible",
    # --- gobierno y servicios publicos ---
    "townhall": "Alcaldia municipal",
    "courthouse": "Juzgado / tribunal",
    "police": "Policia (PNC)",
    "fire_station": "Cuerpo de bomberos",
    "prison": "Centro penal",
    "post_office": "Oficina de correos",
    "post_box": "Buzon de correo",
    "post_depot": "Centro de distribucion postal",
    "public_building": "Edificio publico",
    "embassy": "Embajada",
    "community_centre": "Casa comunal / centro comunitario",
    "social_centre": "Centro social",
    "conference_centre": "Centro de convenciones",
    "events_venue": "Salon de eventos",
    "exhibition_centre": "Centro de exposiciones",
    "ranger_station": "Estacion de guardaparques",
    "refugee_site": "Albergue",
    "shelter": "Refugio / parada cubierta",
    "customs": "Aduana",
    "register_office": "Registro civil",
    # --- comercio y ocio ---
    "marketplace": "Mercado",
    "cinema": "Cine",
    "theatre": "Teatro",
    "nightclub": "Discoteca",
    "stripclub": "Club nocturno para adultos",
    "casino": "Casino",
    "gambling": "Sala de juegos de azar",
    "arts_centre": "Centro de arte y cultura",
    "music_venue": "Sala de conciertos",
    "planetarium": "Planetario",
    "studio": "Estudio (radio / TV / grabacion)",
    "fountain": "Fuente",
    "public_bath": "Bano publico / termas",
    "sauna": "Sauna",
    "brothel": "Prostibulo",
    # --- culto y cementerios ---
    "place_of_worship": "Lugar de culto (iglesia / templo)",
    "monastery": "Monasterio / convento",
    "grave_yard": "Cementerio (junto a iglesia)",
    "funeral_hall": "Capilla velatoria",
    "crematorium": "Crematorio",
    "mortuary": "Morgue",
    # --- servicios y mobiliario urbano ---
    "toilets": "Banos publicos",
    "shower": "Duchas",
    "drinking_water": "Agua potable (bebedero)",
    "water_point": "Punto de agua",
    "watering_place": "Abrevadero",
    "bench": "Banca",
    "waste_basket": "Basurero",
    "waste_disposal": "Contenedor de basura",
    "waste_transfer_station": "Estacion de transferencia de residuos",
    "recycling": "Reciclaje",
    "sanitary_dump_station": "Vaciado sanitario",
    "telephone": "Telefono publico",
    "photo_booth": "Cabina de fotos",
    "clock": "Reloj publico",
    "vending_machine": "Maquina expendedora",
    "give_box": "Caja de donaciones",
    "smoking_area": "Area de fumadores",
    "animal_shelter": "Albergue de animales",
    "animal_boarding": "Pension de mascotas",
    "animal_breeding": "Criadero de animales",
    "veterinary_pharmacy": "Farmacia veterinaria",
    "dog_toilet": "Area sanitaria para perros",
    "dive_centre": "Centro de buceo",
    "kitchen": "Cocina comunitaria",
    "lounger": "Tumbonas",
    "monitoring_station": "Estacion de monitoreo",
    "security_booth": "Caseta de seguridad",
    "yes": "Servicio (sin especificar)",
}

VALORES_LEISURE = {
    "park": "Parque",
    "playground": "Parque infantil / juegos",
    "garden": "Jardin",
    "nature_reserve": "Reserva natural",
    "sports_centre": "Centro deportivo / polideportivo",
    "sports_hall": "Gimnasio cubierto",
    "fitness_centre": "Gimnasio",
    "fitness_station": "Estacion de ejercicios",
    "gym": "Gimnasio (etiqueta antigua)",
    "stadium": "Estadio",
    "pitch": "Cancha",
    "track": "Pista de atletismo / carreras",
    "swimming_pool": "Piscina",
    "swimming_area": "Area para nadar",
    "water_park": "Parque acuatico",
    "beach_resort": "Balneario / complejo de playa",
    "golf_course": "Campo de golf",
    "miniature_golf": "Golf miniatura",
    "disc_golf_course": "Campo de disc golf",
    "bowling_alley": "Boliche",
    "escape_game": "Sala de escape",
    "amusement_arcade": "Sala de maquinas de juego",
    "adult_gaming_centre": "Centro de juegos para adultos",
    "trampoline_park": "Parque de trampolines",
    "marina": "Marina / puerto deportivo",
    "slipway": "Rampa para embarcaciones",
    "dog_park": "Parque para perros",
    "picnic_table": "Mesa de picnic",
    "firepit": "Fogata",
    "bbq": "Area de parrillas",
    "common": "Terreno comunal",
    "dance": "Salon de baile",
    "hackerspace": "Hackerspace",
    "horse_riding": "Equitacion",
    "ice_rink": "Pista de hielo",
    "resort": "Complejo turistico",
    "bird_hide": "Observatorio de aves",
    "wildlife_hide": "Observatorio de fauna",
    "bandstand": "Kiosco de musica",
    "sauna": "Sauna",
    "summer_camp": "Campamento de verano",
    "outdoor_seating": "Area de mesas al aire libre",
    "fishing": "Area de pesca",
    "bleachers": "Graderias",
    "tanning_salon": "Salon de bronceado",
    "club": "Club recreativo",
    "yes": "Area recreativa (sin especificar)",
}

VALORES_TOURISM = {
    "hotel": "Hotel",
    "motel": "Motel",
    "hostel": "Hostal",
    "guest_house": "Casa de huespedes",
    "bed_and_breakfast": "Bed and breakfast",
    "apartment": "Apartamento turistico",
    "chalet": "Cabana / chalet",
    "alpine_hut": "Refugio de montana",
    "wilderness_hut": "Cabana rustica",
    "camp_site": "Camping",
    "camp_pitch": "Parcela de camping",
    "caravan_site": "Area de casas rodantes",
    "attraction": "Atraccion turistica",
    "theme_park": "Parque de diversiones",
    "zoo": "Zoologico",
    "aquarium": "Acuario",
    "museum": "Museo",
    "gallery": "Galeria de arte",
    "artwork": "Obra de arte / escultura",
    "viewpoint": "Mirador",
    "information": "Informacion turistica",
    "picnic_site": "Area de picnic",
    "trail_riding_station": "Estacion de cabalgata",
    "love_hotel": "Auto hotel",
    "hostal": "Hostal",
    "yes": "Turismo (sin especificar)",
}

VALORES_HEALTHCARE = {
    "hospital": "Hospital",
    "clinic": "Clinica",
    "doctor": "Medico / consultorio",
    "dentist": "Dentista",
    "pharmacy": "Farmacia",
    "laboratory": "Laboratorio clinico",
    "sample_collection": "Toma de muestras",
    "physiotherapist": "Fisioterapia",
    "psychotherapist": "Psicoterapia",
    "alternative": "Medicina alternativa",
    "blood_donation": "Donacion de sangre",
    "blood_bank": "Banco de sangre",
    "rehabilitation": "Rehabilitacion",
    "optometrist": "Optometria / optica",
    "dialysis": "Dialisis",
    "vaccination_centre": "Centro de vacunacion",
    "centre": "Centro de salud",
    "birthing_centre": "Centro de partos",
    "midwife": "Partera",
    "nurse": "Enfermeria",
    "occupational_therapist": "Terapia ocupacional",
    "podiatrist": "Podologia",
    "speech_therapist": "Terapia del lenguaje",
    "counselling": "Consejeria / orientacion",
    "hospice": "Hospicio",
    "community_health_worker": "Promotor de salud",
    "audiologist": "Audiologia",
    "nutrition_counselling": "Nutricion",
    "radiology": "Radiologia / imagenes",
    "emergency": "Emergencias",
    "yes": "Servicio de salud (sin especificar)",
}

VALORES_SPORT = {
    "soccer": "Futbol",
    "football": "Futbol",
    "futsal": "Futbol sala",
    "basketball": "Basquetbol",
    "baseball": "Beisbol",
    "softball": "Softbol",
    "volleyball": "Voleibol",
    "beachvolleyball": "Voleibol de playa",
    "swimming": "Natacion",
    "water_polo": "Waterpolo",
    "tennis": "Tenis",
    "table_tennis": "Tenis de mesa / ping pong",
    "padel": "Padel",
    "pickleball": "Pickleball",
    "badminton": "Badminton",
    "racquet": "Deportes de raqueta",
    "squash": "Squash",
    "cycling": "Ciclismo",
    "bmx": "BMX",
    "mtb": "Ciclismo de montana",
    "surfing": "Surf",
    "kitesurfing": "Kitesurf",
    "windsurfing": "Windsurf",
    "skateboard": "Patineta / skate",
    "roller_skating": "Patinaje",
    "skating": "Patinaje",
    "boxing": "Boxeo",
    "martial_arts": "Artes marciales",
    "karate": "Karate",
    "taekwondo": "Taekwondo",
    "judo": "Judo",
    "wrestling": "Lucha",
    "weightlifting": "Levantamiento de pesas",
    "crossfit": "Crossfit",
    "fitness": "Acondicionamiento fisico",
    "gymnastics": "Gimnasia",
    "athletics": "Atletismo",
    "running": "Atletismo / carrera",
    "triathlon": "Triatlon",
    "golf": "Golf",
    "karting": "Karting",
    "motor": "Automovilismo",
    "motocross": "Motocross",
    "horse_racing": "Carreras de caballos",
    "equestrian": "Equitacion",
    "archery": "Tiro con arco",
    "shooting": "Tiro deportivo",
    "billiards": "Billar",
    "tenpin_bowling": "Boliche",
    "bowls": "Bochas",
    "chess": "Ajedrez",
    "climbing": "Escalada",
    "canoe": "Canotaje",
    "kayak": "Kayak",
    "rowing": "Remo",
    "sailing": "Vela",
    "scuba_diving": "Buceo",
    "fishing": "Pesca deportiva",
    "handball": "Balonmano",
    "hockey": "Hockey",
    "field_hockey": "Hockey sobre cesped",
    "rugby": "Rugby",
    "rugby_union": "Rugby union",
    "cricket": "Cricket",
    "american_football": "Futbol americano",
    "dance": "Danza",
    "yoga": "Yoga",
    "paintball": "Paintball",
    "airsoft": "Airsoft",
    "multi": "Multideportivo",
    "free_flying": "Parapente / vuelo libre",
    "obstacle_course": "Pista de obstaculos",
}

VALORES_CUISINE = {
    "pupusa": "Pupuseria",
    "pupuseria": "Pupuseria",
    "regional": "Comida tipica / regional",
    "local": "Comida local",
    "salvadoran": "Comida salvadorena",
    "latin_american": "Comida latinoamericana",
    "mexican": "Mexicana",
    "tacos": "Tacos",
    "burrito": "Burritos",
    "pizza": "Pizza",
    "burger": "Hamburguesas",
    "chicken": "Pollo",
    "fried_chicken": "Pollo frito",
    "wings": "Alitas",
    "hot_dog": "Hot dogs",
    "sandwich": "Sandwiches",
    "seafood": "Mariscos",
    "fish": "Pescado",
    "sushi": "Sushi",
    "japanese": "Japonesa",
    "ramen": "Ramen",
    "poke": "Poke",
    "chinese": "China",
    "asian": "Asiatica",
    "thai": "Tailandesa",
    "korean": "Coreana",
    "italian": "Italiana",
    "pasta": "Pasta",
    "spanish": "Espanola",
    "american": "Americana",
    "steak_house": "Carnes / steak house",
    "barbecue": "Barbacoa",
    "grill": "Parrilla",
    "breakfast": "Desayunos",
    "brunch": "Brunch",
    "coffee_shop": "Cafeteria",
    "cake": "Pasteles",
    "dessert": "Postres",
    "ice_cream": "Helados",
    "donut": "Donas",
    "crepe": "Crepas",
    "waffle": "Wafles",
    "bubble_tea": "Bubble tea",
    "juice": "Jugos y licuados",
    "smoothie": "Batidos",
    "vegetarian": "Vegetariana",
    "vegan": "Vegana",
    "salad": "Ensaladas",
    "soup": "Sopas",
    "noodle": "Fideos",
    "empanada": "Empanadas",
    "arepa": "Arepas",
    "international": "Internacional",
    "fusion": "Fusion",
    "french": "Francesa",
    "peruvian": "Peruana",
    "brazilian": "Brasilena",
    "argentinian": "Argentina",
    "colombian": "Colombiana",
    "indian": "India",
    "arab": "Arabe",
    "lebanese": "Libanesa",
    "turkish": "Turca",
    "greek": "Griega",
    "mediterranean": "Mediterranea",
    "buffet": "Bufe",
    "snack": "Bocadillos",
    "bakery": "Panaderia",
}

VALORES_CLUB = {
    "sport": "Club deportivo",
    "social": "Club social",
    "culture": "Club cultural",
    "cultural": "Club cultural",
    "scout": "Scouts",
    "rotary": "Club Rotario",
    "lions": "Club de Leones",
    "nautical": "Club nautico",
    "yacht": "Club de yates",
    "sailing": "Club de vela",
    "automobile": "Club automovilistico",
    "motorcycle": "Club de motociclismo",
    "music": "Club de musica",
    "art": "Club de arte",
    "theatre": "Club de teatro",
    "photography": "Club de fotografia",
    "chess": "Club de ajedrez",
    "game": "Club de juegos",
    "board_games": "Club de juegos de mesa",
    "veterans": "Club de veteranos",
    "charity": "Club de beneficencia",
    "ethnic": "Club etnico / de colonia",
    "religion": "Club religioso",
    "student": "Club estudiantil",
    "youth": "Club juvenil",
    "senior": "Club de adultos mayores",
    "fan": "Club de aficionados",
    "shooting": "Club de tiro",
    "fishing": "Club de pesca",
    "hunting": "Club de caza",
    "computer": "Club de computacion",
    "astronomy": "Club de astronomia",
    "dance": "Club de baile",
    "cinema": "Cine club",
    "history": "Club de historia",
    "nature": "Club de naturaleza",
    "gardening": "Club de jardineria",
    "business": "Club empresarial",
    "linux": "Club de tecnologia",
    "yes": "Club (sin especificar)",
}

VALORES_BUILDING = {
    "house": "Casa",
    "detached": "Casa independiente",
    "semidetached_house": "Casa duplex",
    "terrace": "Casas en hilera",
    "residential": "Edificio residencial",
    "apartments": "Apartamentos",
    "bungalow": "Bungalow",
    "dormitory": "Residencia estudiantil",
    "hut": "Champa / choza",
    "cabin": "Cabana",
    "static_caravan": "Casa movil",
    "commercial": "Edificio comercial",
    "retail": "Local comercial / retail",
    "kiosk": "Kiosco",
    "supermarket": "Supermercado",
    "office": "Edificio de oficinas",
    "industrial": "Edificio industrial",
    "warehouse": "Bodega",
    "factory": "Fabrica",
    "manufacture": "Planta de manufactura",
    "hotel": "Hotel",
    "school": "Escuela",
    "kindergarten": "Kinder",
    "university": "Universidad",
    "college": "Instituto / college",
    "hospital": "Hospital",
    "clinic": "Clinica",
    "church": "Iglesia",
    "chapel": "Capilla",
    "cathedral": "Catedral",
    "mosque": "Mezquita",
    "temple": "Templo",
    "synagogue": "Sinagoga",
    "religious": "Edificio religioso",
    "government": "Edificio de gobierno",
    "civic": "Edificio civico",
    "public": "Edificio publico",
    "fire_station": "Estacion de bomberos",
    "police": "Edificio policial",
    "prison": "Centro penal",
    "transportation": "Edificio de transporte",
    "train_station": "Estacion de tren",
    "parking": "Edificio de estacionamiento",
    "garage": "Garaje",
    "garages": "Garajes",
    "carport": "Cochera",
    "shed": "Cobertizo / galera",
    "barn": "Granero",
    "farm": "Casa de finca",
    "farm_auxiliary": "Edificio agricola auxiliar",
    "greenhouse": "Invernadero",
    "stable": "Establo",
    "sty": "Porqueriza",
    "hangar": "Hangar",
    "silo": "Silo",
    "storage_tank": "Tanque de almacenamiento",
    "water_tower": "Tanque elevado de agua",
    "service": "Edificio de servicio",
    "roof": "Techado (sin paredes)",
    "ruins": "Edificio en ruinas",
    "construction": "En construccion",
    "stadium": "Estadio",
    "sports_hall": "Gimnasio cubierto",
    "sports_centre": "Centro deportivo",
    "grandstand": "Graderia",
    "pavilion": "Pabellon",
    "toilets": "Servicios sanitarios",
    "bunker": "Bunker",
    "tower": "Torre",
    "transformer_tower": "Caseta de transformador",
    "gatehouse": "Caseta de acceso",
    "boathouse": "Casa de botes",
    "container": "Contenedor",
    "allotment_house": "Casa de huerto",
    "yes": "Edificio (sin especificar)",
}

VALORES_LANDUSE = {
    "commercial": "Zona comercial",
    "retail": "Zona de comercio al detalle (retail)",
    "industrial": "Zona industrial",
    "residential": "Zona residencial",
    "farmland": "Cultivos",
    "farmyard": "Patio de finca",
    "orchard": "Huerto / plantacion",
    "plant_nursery": "Vivero",
    "vineyard": "Vinedo",
    "meadow": "Pastizal",
    "forest": "Bosque gestionado",
    "grass": "Cesped",
    "greenfield": "Terreno sin desarrollar",
    "brownfield": "Terreno baldio industrial",
    "construction": "En construccion",
    "landfill": "Relleno sanitario",
    "quarry": "Cantera",
    "salt_pond": "Salinera",
    "aquaculture": "Acuicultura / camaroneras",
    "basin": "Pila / estanque artificial",
    "reservoir": "Embalse",
    "military": "Zona militar",
    "religious": "Terreno religioso",
    "cemetery": "Cementerio",
    "allotments": "Huertos urbanos",
    "village_green": "Plaza comunal",
    "recreation_ground": "Area recreativa",
    "education": "Zona educativa",
    "institutional": "Zona institucional",
    "garages": "Garajes",
    "greenhouse_horticulture": "Invernaderos",
    "depot": "Deposito / plantel",
    "port": "Zona portuaria",
    "railway": "Zona ferroviaria",
    "flowerbed": "Jardinera",
    "logging": "Zona de tala",
    "animal_keeping": "Crianza de animales",
    "yes": "Uso de suelo (sin especificar)",
}

VALORES_PLACE = {
    "country": "Pais",
    "state": "Departamento / estado",
    "region": "Region",
    "province": "Provincia",
    "county": "Departamento (county)",
    "municipality": "Municipio",
    "district": "Distrito",
    "city": "Ciudad",
    "borough": "Distrito urbano",
    "town": "Pueblo / ciudad pequena",
    "village": "Canton / villa",
    "hamlet": "Caserio",
    "isolated_dwelling": "Vivienda aislada",
    "farm": "Finca / hacienda",
    "suburb": "Colonia / barrio (suburbio)",
    "quarter": "Sector / reparto",
    "neighbourhood": "Colonia / vecindario",
    "city_block": "Manzana",
    "plot": "Lote",
    "allotments": "Parcelas",
    "locality": "Localidad",
    "square": "Plaza",
    "island": "Isla",
    "islet": "Islote",
    "archipelago": "Archipielago",
    "sea": "Mar",
    "ocean": "Oceano",
    "continent": "Continente",
}

VALORES_NATURAL = {
    "beach": "Playa",
    "volcano": "Volcan",
    "peak": "Cerro / cumbre",
    "hill": "Colina",
    "ridge": "Cresta / cordillera",
    "cliff": "Acantilado / farallon",
    "valley": "Valle",
    "saddle": "Portillo / collado",
    "water": "Cuerpo de agua (lago / laguna / rio)",
    "bay": "Bahia",
    "strait": "Estrecho",
    "cape": "Cabo / punta",
    "coastline": "Linea de costa",
    "wetland": "Humedal (incluye manglar)",
    "mangrove": "Manglar",
    "scrub": "Matorral",
    "heath": "Brezal",
    "grassland": "Pastizal natural",
    "wood": "Bosque natural",
    "tree": "Arbol",
    "tree_row": "Hilera de arboles",
    "shrub": "Arbusto",
    "sand": "Arenal",
    "dune": "Duna",
    "rock": "Roca",
    "bare_rock": "Roca desnuda",
    "stone": "Piedra",
    "scree": "Pedregal",
    "sinkhole": "Sumidero",
    "cave_entrance": "Entrada de cueva",
    "spring": "Manantial / nacimiento",
    "hot_spring": "Aguas termales",
    "geyser": "Geiser",
    "reef": "Arrecife",
    "shoal": "Banco de arena",
    "isthmus": "Istmo",
    "mud": "Lodazal",
    "crater": "Crater",
    "gully": "Quebrada / barranco",
    "cliff_edge": "Borde de acantilado",
    "glacier": "Glaciar",
}

VALORES_HISTORIC = {
    "monument": "Monumento",
    "memorial": "Memorial",
    "ruins": "Ruinas",
    "archaeological_site": "Sitio arqueologico",
    "fort": "Fuerte",
    "castle": "Castillo",
    "building": "Edificio historico",
    "church": "Iglesia historica",
    "city_gate": "Puerta de ciudad",
    "tomb": "Tumba",
    "wayside_cross": "Cruz de camino",
    "wayside_shrine": "Ermita / capilla de camino",
    "boundary_stone": "Mojon / piedra limite",
    "milestone": "Hito kilometrico",
    "aircraft": "Aeronave historica",
    "locomotive": "Locomotora historica",
    "railway_car": "Vagon historico",
    "ship": "Barco historico",
    "wreck": "Naufragio",
    "tank": "Tanque militar historico",
    "cannon": "Canon historico",
    "mine": "Mina historica",
    "mine_shaft": "Pozo de mina historico",
    "manor": "Casona / hacienda historica",
    "farm": "Finca historica",
    "house": "Casa historica",
    "district": "Centro historico",
    "battlefield": "Campo de batalla",
    "heritage": "Patrimonio",
    "pillory": "Picota",
    "yes": "Sitio historico (sin especificar)",
}

VALORES_MAN_MADE = {
    "tower": "Torre",
    "communications_tower": "Torre de comunicaciones",
    "mast": "Mastil / antena",
    "antenna": "Antena",
    "water_tower": "Tanque elevado de agua",
    "storage_tank": "Tanque de almacenamiento",
    "water_tank": "Tanque de agua",
    "reservoir_covered": "Cisterna cubierta",
    "water_well": "Pozo de agua",
    "water_works": "Planta potabilizadora",
    "water_treatment": "Planta de tratamiento de agua",
    "wastewater_plant": "Planta de aguas residuales",
    "water_tap": "Grifo / chorro publico",
    "pumping_station": "Estacion de bombeo",
    "pipeline": "Tuberia / poliducto",
    "pier": "Muelle",
    "breakwater": "Rompeolas",
    "groyne": "Espigon",
    "lighthouse": "Faro",
    "beacon": "Baliza",
    "silo": "Silo",
    "chimney": "Chimenea",
    "works": "Planta industrial",
    "surveillance": "Camara de vigilancia",
    "street_cabinet": "Gabinete de calle",
    "utility_pole": "Poste de servicios",
    "monitoring_station": "Estacion de monitoreo",
    "crane": "Grua",
    "bridge": "Puente (estructura)",
    "embankment": "Terraplen",
    "dyke": "Dique",
    "cutline": "Brecha",
    "flagpole": "Asta de bandera",
    "gasometer": "Gasometro",
    "kiln": "Horno",
    "mineshaft": "Pozo de mina",
    "adit": "Bocamina",
    "petroleum_well": "Pozo petrolero",
    "satellite_dish": "Antena parabolica",
    "telescope": "Telescopio",
    "windmill": "Molino de viento",
    "watermill": "Molino de agua",
    "goods_conveyor": "Transportador de carga",
    "cooling_tower": "Torre de enfriamiento",
    "wildlife_crossing": "Paso de fauna",
    "obelisk": "Obelisco",
    "observatory": "Observatorio",
    "storage": "Almacenamiento",
    "yes": "Estructura artificial (sin especificar)",
}

VALORES_PUBLIC_TRANSPORT = {
    "stop_position": "Punto de parada",
    "platform": "Plataforma / parada",
    "station": "Estacion",
    "stop_area": "Area de parada",
    "stop_area_group": "Grupo de areas de parada",
    "bus_stop": "Parada de bus",
    "bus_station": "Terminal de buses",
    "taxi": "Parada de taxis",
    "ferry_terminal": "Terminal de ferry",
    "yes": "Transporte publico (sin especificar)",
}

VALORES_AEROWAY = {
    "aerodrome": "Aeropuerto / aerodromo",
    "terminal": "Terminal aerea",
    "runway": "Pista de aterrizaje",
    "taxiway": "Calle de rodaje",
    "apron": "Plataforma de estacionamiento",
    "helipad": "Helipuerto (plataforma)",
    "heliport": "Helipuerto",
    "hangar": "Hangar",
    "gate": "Puerta de embarque",
    "navigationaid": "Ayuda a la navegacion",
    "windsock": "Manga de viento",
    "jet_bridge": "Pasarela de embarque",
    "holding_position": "Posicion de espera",
    "parking_position": "Posicion de estacionamiento",
    "fuel": "Abastecimiento de combustible aereo",
}

VALORES_EMERGENCY = {
    "fire_hydrant": "Hidrante",
    "defibrillator": "Desfibrilador (DEA)",
    "ambulance_station": "Base de ambulancias",
    "assembly_point": "Punto de reunion",
    "lifeguard": "Salvavidas",
    "lifeguard_base": "Base de salvavidas",
    "lifeguard_tower": "Torre de salvavidas",
    "life_ring": "Aro salvavidas",
    "water_rescue": "Rescate acuatico",
    "mountain_rescue": "Rescate de montana",
    "phone": "Telefono de emergencia",
    "siren": "Sirena de alerta",
    "access_point": "Punto de acceso de emergencia",
    "fire_extinguisher": "Extintor",
    "fire_hose": "Manguera contra incendios",
    "fire_alarm_box": "Alarma de incendios",
    "fire_water_pond": "Reserva de agua contra incendios",
    "suction_point": "Punto de succion",
    "first_aid_kit": "Botiquin",
    "emergency_ward_entrance": "Entrada de emergencias",
    "landing_site": "Zona de aterrizaje de emergencia",
    "disaster_response": "Respuesta a desastres",
    "yes": "Elemento de emergencia (sin especificar)",
}

VALORES_BRAND = {}  # los valores de `brand` son nombres libres de marca/cadena

# --------------------------------------------------------------------------- #
# Registro de categorias
# --------------------------------------------------------------------------- #
# Cada entrada define:
#   grupo             -> agrupacion tematica solicitada
#   etiqueta          -> nombre de la categoria en espanol
#   llave             -> llave OSM principal (tambien define la subcategoria)
#   valores           -> diccionario valor OSM -> nombre en espanol
#   selectores        -> filtros Overpass adicionales (ademas de ["llave"])
#   llaves_subcat     -> orden de llaves para deducir la subcategoria
#   division_inicial  -> N: la consulta se parte en NxN mosaicos (quadtree).
#                        El script subdivide mas si el servidor se satura.
#   campos_extra      -> etiquetas OSM que se promueven a columnas propias

CATEGORIAS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()


def _cat(
    clave: str,
    grupo: str,
    etiqueta: str,
    valores: Dict[str, str],
    llave: Optional[str] = None,
    selectores: Optional[List[str]] = None,
    llaves_subcat: Optional[List[str]] = None,
    division_inicial: int = 1,
    campos_extra: Optional[List[str]] = None,
    archivo: Optional[str] = None,
) -> None:
    llave = llave or clave
    CATEGORIAS[clave] = {
        "clave": clave,
        "grupo": grupo,
        "etiqueta": etiqueta,
        "llave": llave,
        "valores": valores,
        "selectores": selectores or ['["%s"]' % llave],
        "llaves_subcat": llaves_subcat or [llave],
        "division_inicial": division_inicial,
        "campos_extra": campos_extra or [],
        "archivo": archivo or clave,
    }


# --- 1. Negocios y comercio ------------------------------------------------ #
_cat("shop", "Negocios y comercio", "Comercios y tiendas", VALORES_SHOP,
     division_inicial=1,
     campos_extra=["brand", "operator", "cuisine", "organic", "second_hand",
                   "self_service", "delivery", "takeaway", "drive_through"],
     archivo="01_shop_comercios_y_tiendas")

_cat("office", "Negocios y comercio", "Oficinas y empresas", VALORES_OFFICE,
     division_inicial=1,
     campos_extra=["brand", "operator", "operator:type", "government",
                   "diplomatic", "company", "healthcare"],
     archivo="02_office_oficinas_y_empresas")

_cat("craft", "Negocios y comercio", "Talleres y oficios", VALORES_CRAFT,
     division_inicial=1,
     campos_extra=["brand", "operator", "product", "service"],
     archivo="03_craft_talleres_y_oficios")

_cat("brand", "Negocios y comercio", "Marcas y cadenas", VALORES_BRAND,
     division_inicial=2,
     campos_extra=["brand", "brand:wikidata", "operator", "shop", "amenity",
                   "office", "craft", "cuisine"],
     archivo="04_brand_marcas_y_cadenas")

_cat("industrial", "Negocios y comercio", "Industria", VALORES_INDUSTRIAL,
     division_inicial=1,
     selectores=['["industrial"]', '["man_made"="works"]'],
     llaves_subcat=["industrial", "man_made"],
     campos_extra=["operator", "product", "landuse", "building"],
     archivo="05_industrial_industria")

# --- 2. Servicios y equipamientos ----------------------------------------- #
_cat("amenity", "Servicios y equipamientos", "Servicios y equipamientos",
     VALORES_AMENITY,
     division_inicial=2,
     campos_extra=["brand", "operator", "operator:type", "cuisine", "religion",
                   "denomination", "healthcare", "isced:level", "school",
                   "capacity", "fuel:diesel", "fuel:octane_91",
                   "fuel:octane_95", "parking", "fee", "access", "outdoor_seating",
                   "takeaway", "delivery", "drive_through", "atm",
                   "self_service", "recycling_type", "network"],
     archivo="06_amenity_servicios")

# --- 3. Ocio, turismo y deporte ------------------------------------------- #
_cat("leisure", "Ocio, turismo y deporte", "Ocio y recreacion", VALORES_LEISURE,
     division_inicial=1,
     campos_extra=["sport", "operator", "access", "fee", "surface", "lit",
                   "capacity", "brand"],
     archivo="07_leisure_ocio_y_recreacion")

_cat("tourism", "Ocio, turismo y deporte", "Turismo y hospedaje", VALORES_TOURISM,
     division_inicial=1,
     campos_extra=["brand", "operator", "stars", "rooms", "beds",
                   "internet_access", "attraction", "information", "museum",
                   "artwork_type"],
     archivo="08_tourism_turismo_y_hospedaje")

_cat("sport", "Ocio, turismo y deporte", "Deportes practicados", VALORES_SPORT,
     division_inicial=1,
     campos_extra=["leisure", "building", "surface", "lit", "operator",
                   "access", "club"],
     archivo="09_sport_deportes")

_cat("cuisine", "Ocio, turismo y deporte", "Tipo de cocina", VALORES_CUISINE,
     division_inicial=1,
     campos_extra=["amenity", "shop", "brand", "operator", "takeaway",
                   "delivery", "outdoor_seating", "diet:vegetarian",
                   "diet:vegan"],
     archivo="10_cuisine_tipo_de_cocina")

_cat("club", "Ocio, turismo y deporte", "Clubes", VALORES_CLUB,
     division_inicial=1,
     campos_extra=["sport", "operator", "leisure", "amenity"],
     archivo="11_club_clubes")

# --- 4. Salud -------------------------------------------------------------- #
_cat("healthcare", "Salud", "Salud", VALORES_HEALTHCARE,
     division_inicial=1,
     campos_extra=["healthcare:speciality", "amenity", "operator",
                   "operator:type", "emergency", "beds", "dispensing",
                   "brand"],
     archivo="12_healthcare_salud")

# --- 5. Territorio y edificios -------------------------------------------- #
_cat("building", "Territorio y edificios", "Tipo de edificio", VALORES_BUILDING,
     division_inicial=4,
     campos_extra=["building:levels", "building:material", "roof:material",
                   "height", "amenity", "shop", "office", "addr:housenumber",
                   "start_date", "construction"],
     archivo="13_building_edificios")

_cat("landuse", "Territorio y edificios", "Uso del suelo", VALORES_LANDUSE,
     division_inicial=2,
     campos_extra=["crop", "produce", "operator", "leisure", "industrial",
                   "aquaculture", "resource"],
     archivo="14_landuse_uso_del_suelo")

_cat("place", "Territorio y edificios", "Lugares poblados", VALORES_PLACE,
     division_inicial=1,
     campos_extra=["population", "admin_level", "is_in", "capital",
                   "place:CN", "ref"],
     archivo="15_place_lugares_poblados")

_cat("natural", "Territorio y edificios", "Elementos naturales", VALORES_NATURAL,
     division_inicial=2,
     campos_extra=["water", "wetland", "ele", "intermittent", "salt",
                   "leaf_type", "surface", "protect_class"],
     archivo="16_natural_elementos_naturales")

_cat("historic", "Territorio y edificios", "Patrimonio historico", VALORES_HISTORIC,
     division_inicial=1,
     campos_extra=["heritage", "heritage:operator", "inscription", "start_date",
                   "memorial", "ruins", "site_type", "tourism"],
     archivo="17_historic_patrimonio")

_cat("man_made", "Territorio y edificios", "Obras y estructuras", VALORES_MAN_MADE,
     division_inicial=2,
     campos_extra=["operator", "tower:type", "height", "material",
                   "surveillance", "surveillance:type", "communication:mobile_phone",
                   "content", "substance"],
     archivo="18_man_made_obras_y_estructuras")

# --- 6. Transporte y emergencias ------------------------------------------ #
_cat("public_transport", "Transporte y emergencias", "Transporte publico",
     VALORES_PUBLIC_TRANSPORT,
     division_inicial=2,
     selectores=['["public_transport"]', '["highway"="bus_stop"]',
                 '["amenity"="bus_station"]', '["amenity"="ferry_terminal"]'],
     llaves_subcat=["public_transport", "highway", "amenity"],
     campos_extra=["highway", "amenity", "bus", "shelter", "bench", "operator",
                   "network", "route_ref", "ref", "railway"],
     archivo="19_public_transport_transporte")

_cat("aeroway", "Transporte y emergencias", "Aeropuertos y aviacion", VALORES_AEROWAY,
     division_inicial=1,
     campos_extra=["iata", "icao", "operator", "surface", "ref", "length",
                   "aerodrome:type"],
     archivo="20_aeroway_aviacion")

_cat("emergency", "Transporte y emergencias", "Emergencias", VALORES_EMERGENCY,
     division_inicial=2,
     campos_extra=["fire_hydrant:type", "fire_hydrant:diameter", "operator",
                   "access", "defibrillator:location", "colour", "ref"],
     archivo="21_emergency_emergencias")


#: Columnas fijas que llevan todos los archivos (en este orden).
COLUMNAS_BASE = [
    "categoria",
    "categoria_es",
    "grupo",
    "subcategoria",
    "subcategoria_es",
    "nombre",
    "nombre_alterno",
    "marca",
    "operador",
    "latitud",
    "longitud",
    "departamento",
    "municipio",
    "distrito",
    "unidades_administrativas",
    "direccion",
    "calle",
    "numero",
    "colonia_barrio",
    "ciudad",
    "codigo_postal",
    "telefono",
    "celular_whatsapp",
    "correo",
    "sitio_web",
    "facebook",
    "horario",
    "cocina",
    "deporte",
    "religion",
    "accesibilidad",
    "internet",
    "acepta_tarjeta",
    "niveles_edificio",
    "capacidad",
    "wikidata",
    "codigo_referencia",
    "descripcion",
    "fuente_osm",
    "osm_tipo",
    "osm_id",
    "osm_url",
    "fecha_consulta",
]

#: Mapa columna fija -> lista de etiquetas OSM candidatas (primera que exista).
MAPA_COLUMNAS = {
    "nombre": ["name", "name:es", "official_name", "int_name", "brand", "operator"],
    "nombre_alterno": ["alt_name", "short_name", "old_name", "loc_name", "name:en"],
    "marca": ["brand", "brand:wikidata"],
    "operador": ["operator", "operator:type"],
    "direccion": ["addr:full", "address"],
    "calle": ["addr:street"],
    "numero": ["addr:housenumber"],
    "colonia_barrio": ["addr:neighbourhood", "addr:suburb", "addr:quarter",
                       "addr:hamlet", "addr:place"],
    "ciudad": ["addr:city", "addr:town", "addr:municipality", "addr:district"],
    "codigo_postal": ["addr:postcode", "postal_code"],
    "telefono": ["phone", "contact:phone", "telephone", "phone:mobile"],
    "celular_whatsapp": ["contact:mobile", "mobile", "contact:whatsapp", "whatsapp"],
    "correo": ["email", "contact:email"],
    "sitio_web": ["website", "contact:website", "url", "contact:url"],
    "facebook": ["contact:facebook", "facebook", "contact:instagram", "instagram"],
    "horario": ["opening_hours", "service_times", "opening_hours:covid19"],
    "cocina": ["cuisine"],
    "deporte": ["sport"],
    "religion": ["religion", "denomination"],
    "accesibilidad": ["wheelchair", "wheelchair:description"],
    "internet": ["internet_access", "internet_access:fee", "wifi"],
    "acepta_tarjeta": ["payment:credit_cards", "payment:debit_cards",
                       "payment:cards", "payment:cash", "payment:visa"],
    "niveles_edificio": ["building:levels", "levels"],
    "capacidad": ["capacity", "rooms", "beds", "seats"],
    "wikidata": ["wikidata", "brand:wikidata", "operator:wikidata"],
    "codigo_referencia": ["ref", "ref:MINSAL", "ref:MINED", "ref:isil", "ref:vatin"],
    "descripcion": ["description", "note", "description:es", "inscription"],
    "fuente_osm": ["source", "source:name", "survey:date"],
}


# --------------------------------------------------------------------------- #
# Utilidades generales
# --------------------------------------------------------------------------- #

def normalizar(texto: str) -> str:
    """minusculas, sin acentos y sin espacios extra (para comparar nombres)."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().lower()


def titulo_legible(valor: str) -> str:
    """`shoe_repair` -> `Shoe repair` (para valores OSM sin traduccion)."""
    if not valor:
        return ""
    limpio = str(valor).replace("_", " ").replace(";", " / ").strip()
    return limpio[:1].upper() + limpio[1:]


def etiqueta_subcategoria(cat: Dict[str, Any], valor: str) -> str:
    """Traduce el valor OSM al espanol; si no esta en la tabla, lo hace legible."""
    if not valor:
        return ""
    tabla = cat["valores"]
    if valor in tabla:
        return tabla[valor]
    # valores multiples separados por ; (ej. cuisine=pizza;burger)
    if ";" in valor:
        partes = [tabla.get(p.strip(), titulo_legible(p.strip()))
                  for p in valor.split(";") if p.strip()]
        return " / ".join(partes)
    return titulo_legible(valor)


def log(mensaje: str, silencioso: bool = False) -> None:
    if not silencioso:
        marca = _dt.datetime.now().strftime("%H:%M:%S")
        print("[%s] %s" % (marca, mensaje), flush=True)


def _sanear_celda(valor: Any) -> Any:
    """Excel no acepta celdas de mas de 32767 caracteres ni caracteres de control."""
    if isinstance(valor, str):
        if len(valor) > 32000:
            valor = valor[:32000] + " ...[truncado]"
        valor = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", valor)
    return valor


# --------------------------------------------------------------------------- #
# Cliente Overpass
# --------------------------------------------------------------------------- #

class ErrorOverpass(RuntimeError):
    """Error no recuperable de la consulta (sintaxis, area inexistente, ...)."""


class ErrorSaturacion(RuntimeError):
    """El servidor no pudo completar la consulta: hay que dividirla."""


class ErrorDependencia(RuntimeError):
    """Falta una libreria de Python necesaria para continuar."""


class ClienteOverpass:
    def __init__(
        self,
        endpoints: Sequence[str] = ENDPOINTS_OVERPASS,
        dir_cache: Optional[str] = DIR_CACHE_DEF,
        pausa: float = 2.0,
        timeout_consulta: int = 600,
        timeout_http: int = 900,
        max_reintentos: int = 4,
        silencioso: bool = False,
    ) -> None:
        self.endpoints = list(endpoints)
        self.dir_cache = dir_cache
        self.pausa = pausa
        self.timeout_consulta = timeout_consulta
        self.timeout_http = timeout_http
        self.max_reintentos = max_reintentos
        self.silencioso = silencioso
        self.consultas_realizadas = 0
        self.consultas_en_cache = 0
        self.bytes_descargados = 0
        self.marca_datos_osm = ""
        self._ultimo_envio = 0.0
        if self.dir_cache:
            os.makedirs(self.dir_cache, exist_ok=True)

    # -- cache -------------------------------------------------------------- #
    def _ruta_cache(self, ql: str) -> Optional[str]:
        if not self.dir_cache:
            return None
        clave = hashlib.sha1(ql.encode("utf-8")).hexdigest()
        return os.path.join(self.dir_cache, "%s.json" % clave)

    # -- consulta ----------------------------------------------------------- #
    def consultar(self, ql: str, descripcion: str = "",
                  meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ruta = self._ruta_cache(ql)
        if ruta and os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as fh:
                    datos = json.load(fh)
                self.consultas_en_cache += 1
                log("    cache: %s (%d elementos)"
                    % (descripcion or "consulta", len(datos.get("elements", []))),
                    self.silencioso)
                return datos
            except (ValueError, OSError):
                pass  # cache corrupta: se vuelve a consultar

        ultimo_error: Optional[Exception] = None
        for intento in range(1, self.max_reintentos + 1):
            endpoint = self.endpoints[(intento - 1) % len(self.endpoints)]
            try:
                datos = self._enviar(endpoint, ql)
                remark = str(datos.get("remark", ""))
                if "timed out" in remark or "out of memory" in remark:
                    raise ErrorSaturacion(remark)
                marca = (datos.get("osm3s") or {}).get("timestamp_osm_base")
                if marca:
                    self.marca_datos_osm = str(marca)
                # se guarda de que era la consulta, para poder reconstruir los
                # Excel desde la cache sin volver a consultar (--solo-excel)
                datos["_extraer_osm"] = dict(meta or {}, version=VERSION,
                                             descripcion=descripcion)
                if ruta:
                    with open(ruta, "w", encoding="utf-8") as fh:
                        json.dump(datos, fh, ensure_ascii=False)
                return datos
            except ErrorOverpass:
                raise
            except ErrorSaturacion:
                raise
            except Exception as exc:  # red, 429, 504, JSON invalido, ...
                ultimo_error = exc
                espera = min(120, 5 * (2 ** (intento - 1)))
                log("    ! fallo (%s) en %s; reintento %d/%d en %ds"
                    % (exc, urllib.parse.urlsplit(endpoint).netloc, intento,
                       self.max_reintentos, espera), self.silencioso)
                if intento < self.max_reintentos:
                    time.sleep(espera)
        raise ErrorSaturacion("sin exito tras %d intentos: %s"
                              % (self.max_reintentos, ultimo_error))

    def _enviar(self, endpoint: str, ql: str) -> Dict[str, Any]:
        # cortesia con el servidor: pausa entre envios
        transcurrido = time.time() - self._ultimo_envio
        if transcurrido < self.pausa:
            time.sleep(self.pausa - transcurrido)

        cuerpo = urllib.parse.urlencode({"data": ql}).encode("utf-8")
        peticion = urllib.request.Request(
            endpoint,
            data=cuerpo,
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        self._ultimo_envio = time.time()
        self.consultas_realizadas += 1
        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout_http) as resp:
                crudo = resp.read()
        except urllib.error.HTTPError as err:
            detalle = ""
            try:
                detalle = err.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            if err.code in (400,) and "syntax error" in detalle.lower():
                raise ErrorOverpass("consulta invalida: %s" % detalle)
            if err.code in (429, 504, 503, 502):
                raise ErrorSaturacion("HTTP %s: %s" % (err.code, detalle[:120]))
            raise RuntimeError("HTTP %s: %s" % (err.code, detalle[:200]))
        self.bytes_descargados += len(crudo)
        try:
            return json.loads(crudo.decode("utf-8", "replace"))
        except ValueError as exc:
            raise RuntimeError("respuesta no JSON (%s)" % exc)


# --------------------------------------------------------------------------- #
# Geometria: armado de poligonos y point-in-polygon
# --------------------------------------------------------------------------- #

try:  # shapely es opcional (acelera el point-in-polygon)
    from shapely.geometry import Point as _ShpPoint  # type: ignore
    from shapely.geometry import Polygon as _ShpPolygon  # type: ignore
    from shapely.prepared import prep as _shp_prep  # type: ignore
    HAY_SHAPELY = True
except Exception:  # pragma: no cover
    HAY_SHAPELY = False


def _cerrar_anillos(lineas: List[List[Tuple[float, float]]],
                    tolerancia: float = 1e-7) -> List[List[Tuple[float, float]]]:
    """Une tramos (ways) sueltos hasta formar anillos cerrados."""
    pendientes = [list(l) for l in lineas if len(l) >= 2]
    anillos: List[List[Tuple[float, float]]] = []

    def cerca(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) <= tolerancia and abs(a[1] - b[1]) <= tolerancia

    while pendientes:
        actual = pendientes.pop(0)
        if cerca(actual[0], actual[-1]) and len(actual) >= 4:
            anillos.append(actual)
            continue
        progreso = True
        while progreso:
            progreso = False
            for idx, otro in enumerate(pendientes):
                if cerca(actual[-1], otro[0]):
                    actual.extend(otro[1:])
                elif cerca(actual[-1], otro[-1]):
                    actual.extend(list(reversed(otro))[1:])
                elif cerca(actual[0], otro[-1]):
                    actual = otro[:-1] + actual
                elif cerca(actual[0], otro[0]):
                    actual = list(reversed(otro))[:-1] + actual
                else:
                    continue
                pendientes.pop(idx)
                progreso = True
                break
            if cerca(actual[0], actual[-1]) and len(actual) >= 4:
                break
        if len(actual) >= 4:
            if not cerca(actual[0], actual[-1]):
                actual.append(actual[0])  # se cierra a la fuerza
            anillos.append(actual)
    return anillos


def _punto_en_anillo(lat: float, lon: float,
                     anillo: Sequence[Tuple[float, float]]) -> bool:
    """Algoritmo de cruce de rayos (ray casting). anillo = [(lat, lon), ...]."""
    dentro = False
    n = len(anillo)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = anillo[i]
        lat_j, lon_j = anillo[j]
        if ((lon_i > lon) != (lon_j > lon)):
            corte = lat_i + (lon - lon_i) * (lat_j - lat_i) / (lon_j - lon_i)
            if lat < corte:
                dentro = not dentro
        j = i
    return dentro


def _distancia_punto_segmento(lat: float, lon: float,
                              a: Tuple[float, float],
                              b: Tuple[float, float]) -> float:
    """Distancia aproximada (grados) de (lat, lon) al segmento a-b."""
    ay, ax = a
    by, bx = b
    dy, dx = by - ay, bx - ax
    if dy == 0.0 and dx == 0.0:
        return math.hypot(lat - ay, lon - ax)
    t = ((lat - ay) * dy + (lon - ax) * dx) / (dy * dy + dx * dx)
    t = max(0.0, min(1.0, t))
    return math.hypot(lat - (ay + t * dy), lon - (ax + t * dx))


def _punto_en_borde(lat: float, lon: float, anillo: Sequence[Tuple[float, float]],
                    tolerancia: float = 1e-7) -> bool:
    """True si el punto cae (casi) exactamente sobre la linea del anillo."""
    for i in range(len(anillo) - 1):
        if _distancia_punto_segmento(lat, lon, anillo[i], anillo[i + 1]) <= tolerancia:
            return True
    return False


class Area:
    """Area administrativa con su geometria y prueba de contencion de puntos."""

    def __init__(self, nombre: str, nivel: int, rel_id: int,
                 anillos_ext: List[List[Tuple[float, float]]],
                 anillos_int: Optional[List[List[Tuple[float, float]]]] = None,
                 tags: Optional[Dict[str, str]] = None) -> None:
        self.nombre = nombre
        self.nivel = nivel
        self.rel_id = rel_id
        self.tags = tags or {}
        self.anillos_ext = anillos_ext
        self.anillos_int = anillos_int or []
        lats = [p[0] for a in anillos_ext for p in a]
        lons = [p[1] for a in anillos_ext for p in a]
        if lats and lons:
            self.bbox = (min(lats), min(lons), max(lats), max(lons))
        else:
            self.bbox = (0.0, 0.0, 0.0, 0.0)
        self._preparado = None
        if HAY_SHAPELY and anillos_ext:
            poligonos = []
            for ext in anillos_ext:
                huecos = [h for h in self.anillos_int
                          if _punto_en_anillo(h[0][0], h[0][1], ext)]
                try:
                    poligonos.append(_ShpPolygon([(p[1], p[0]) for p in ext],
                                                 [[(q[1], q[0]) for q in h]
                                                  for h in huecos]).buffer(0))
                except Exception:
                    continue
            if poligonos:
                union = poligonos[0]
                for pol in poligonos[1:]:
                    try:
                        union = union.union(pol)
                    except Exception:
                        pass
                self._geom = union
                self._preparado = _shp_prep(union)

    @property
    def area_overpass(self) -> int:
        """Id de area de Overpass para una relacion (3600000000 + id)."""
        return 3600000000 + int(self.rel_id)

    def contiene(self, lat: float, lon: float) -> bool:
        """True si el punto esta dentro del area (el borde cuenta como dentro).

        Los limites administrativos suelen dibujarse sobre calles y rios, asi que
        un POI puede caer exactamente sobre la linea: se considera incluido.
        """
        s, w, n, e = self.bbox
        if not (s - 1e-9 <= lat <= n + 1e-9 and w - 1e-9 <= lon <= e + 1e-9):
            return False
        if self._preparado is not None:
            return bool(self._preparado.covers(_ShpPoint(lon, lat)))
        if any(_punto_en_borde(lat, lon, a) for a in self.anillos_ext):
            return True
        dentro = any(_punto_en_anillo(lat, lon, a) for a in self.anillos_ext)
        if dentro and any(_punto_en_anillo(lat, lon, h) for h in self.anillos_int) \
                and not any(_punto_en_borde(lat, lon, h) for h in self.anillos_int):
            return False
        return dentro

    def distancia_grados(self, lat: float, lon: float) -> float:
        """Distancia aproximada (en grados) del punto al area. 0 si esta dentro."""
        if self._preparado is not None:
            try:
                return float(self._geom.distance(_ShpPoint(lon, lat)))
            except Exception:
                pass
        if self.contiene(lat, lon):
            return 0.0
        mejor = float("inf")
        for anillo in self.anillos_ext:
            for i in range(len(anillo) - 1):
                mejor = min(mejor, _distancia_punto_segmento(
                    lat, lon, anillo[i], anillo[i + 1]))
        return mejor

    def __repr__(self) -> str:  # pragma: no cover
        return "<Area %s (nivel %s, rel %s)>" % (self.nombre, self.nivel, self.rel_id)


def area_desde_relacion(el: Dict[str, Any]) -> Optional[Area]:
    """Construye un `Area` a partir de una relacion devuelta por `out geom`."""
    tags = el.get("tags", {}) or {}
    nombre = (tags.get("name:es") or tags.get("name") or tags.get("official_name")
              or "rel %s" % el.get("id"))
    try:
        nivel = int(tags.get("admin_level", 0))
    except (TypeError, ValueError):
        nivel = 0
    lineas_ext: List[List[Tuple[float, float]]] = []
    lineas_int: List[List[Tuple[float, float]]] = []
    for miembro in el.get("members", []) or []:
        geometria = miembro.get("geometry")
        if not geometria:
            continue
        linea = [(float(p["lat"]), float(p["lon"])) for p in geometria
                 if p and p.get("lat") is not None]
        if len(linea) < 2:
            continue
        rol = (miembro.get("role") or "outer").lower()
        if rol == "inner":
            lineas_int.append(linea)
        elif rol in ("outer", "", "exclave", "enclave"):
            lineas_ext.append(linea)
    if not lineas_ext and not lineas_int:
        return None
    anillos_ext = _cerrar_anillos(lineas_ext)
    anillos_int = _cerrar_anillos(lineas_int)
    if not anillos_ext:
        return None
    return Area(nombre, nivel, int(el.get("id", 0)), anillos_ext, anillos_int, tags)


# --------------------------------------------------------------------------- #
# Resolucion de limites administrativos
# --------------------------------------------------------------------------- #

def obtener_relacion_pais(cli: ClienteOverpass) -> int:
    """Devuelve el id de relacion de El Salvador (admin_level=2)."""
    ql = (
        "[out:json][timeout:%d];\n"
        'rel["boundary"="administrative"]["admin_level"="2"]["ISO3166-1"="%s"];\n'
        "out ids tags;" % (cli.timeout_consulta, PAIS_ISO)
    )
    datos = cli.consultar(ql, "relacion de %s" % PAIS_NOMBRE,
                          meta={"tipo": "pais"})
    elementos = [e for e in datos.get("elements", []) if e.get("type") == "relation"]
    if not elementos:
        ql = (
            "[out:json][timeout:%d];\n"
            'rel["boundary"="administrative"]["admin_level"="2"]["name"="%s"];\n'
            "out ids tags;" % (cli.timeout_consulta, PAIS_NOMBRE)
        )
        datos = cli.consultar(ql, "relacion de %s (por nombre)" % PAIS_NOMBRE,
                              meta={"tipo": "pais"})
        elementos = [e for e in datos.get("elements", [])
                     if e.get("type") == "relation"]
    if not elementos:
        raise ErrorOverpass("no se pudo ubicar el limite de %s en OSM" % PAIS_NOMBRE)
    return int(elementos[0]["id"])


def obtener_departamentos(cli: ClienteOverpass,
                          nombres: Sequence[str]) -> List[Area]:
    """Descarga los departamentos solicitados (admin_level=4) con geometria."""
    rel_pais = obtener_relacion_pais(cli)
    ql = (
        "[out:json][timeout:%d];\n"
        "area(id:%d)->.pais;\n"
        'rel(area.pais)["boundary"="administrative"]["admin_level"="4"];\n'
        "out geom;" % (cli.timeout_consulta, 3600000000 + rel_pais)
    )
    datos = cli.consultar(ql, "departamentos de %s" % PAIS_NOMBRE,
                          meta={"tipo": "limites", "admin_level": 4})
    buscados = [normalizar(n) for n in nombres]
    encontrados: "OrderedDict[str, Area]" = OrderedDict()
    for el in datos.get("elements", []):
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {}) or {}
        nombre = tags.get("name") or ""
        norma = normalizar(nombre)
        for objetivo in buscados:
            if objetivo and (objetivo == norma or objetivo in norma
                             or norma in objetivo):
                area = area_desde_relacion(el)
                if area is not None:
                    encontrados[objetivo] = area
                break
    faltantes = [n for n, objetivo in zip(nombres, buscados)
                 if objetivo not in encontrados]
    if faltantes:
        # Respaldo: buscar por bbox del pais (la base de areas de Overpass se
        # reconstruye periodicamente y puede no tener el area del pais).
        ql = (
            "[out:json][timeout:%d];\n"
            'rel["boundary"="administrative"]["admin_level"="4"]'
            "(%.4f,%.4f,%.4f,%.4f);\n"
            "out geom;" % ((cli.timeout_consulta,) + PAIS_BBOX)
        )
        datos = cli.consultar(ql, "departamentos por bbox (respaldo)",
                              meta={"tipo": "limites", "admin_level": 4})
        for el in datos.get("elements", []):
            if el.get("type") != "relation":
                continue
            tags = el.get("tags", {}) or {}
            iso = tags.get("ISO3166-2", "")
            if iso and not iso.startswith("SV-"):
                continue
            norma = normalizar(tags.get("name") or "")
            for objetivo in buscados:
                if objetivo in encontrados or not objetivo:
                    continue
                if objetivo == norma or objetivo in norma or norma in objetivo:
                    area = area_desde_relacion(el)
                    if area is not None:
                        encontrados[objetivo] = area
                    break
        faltantes = [n for n, objetivo in zip(nombres, buscados)
                     if objetivo not in encontrados]
    if faltantes:
        raise ErrorOverpass(
            "no se encontraron estos departamentos en OSM: %s" % ", ".join(faltantes))
    return [encontrados[o] for o in buscados if o in encontrados]


def obtener_unidades_internas(cli: ClienteOverpass, dep: Area) -> List[Area]:
    """Municipios / distritos (admin_level 5..9) dentro de un departamento."""
    ql = (
        "[out:json][timeout:%d];\n"
        "area(id:%d)->.dep;\n"
        'rel(area.dep)["boundary"="administrative"]'
        '["admin_level"~"^(5|6|7|8|9)$"];\n'
        "out geom;" % (cli.timeout_consulta, dep.area_overpass)
    )
    datos = cli.consultar(ql, "municipios/distritos de %s" % dep.nombre,
                          meta={"tipo": "limites", "departamento": dep.nombre})
    unidades: List[Area] = []
    for el in datos.get("elements", []):
        if el.get("type") != "relation":
            continue
        area = area_desde_relacion(el)
        if area is not None:
            unidades.append(area)
    unidades.sort(key=lambda a: (a.nivel, normalizar(a.nombre)))
    return unidades


class Localizador:
    """Asigna departamento / municipio / distrito a un punto (lat, lon)."""

    def __init__(self, dep: Area, unidades: Sequence[Area]) -> None:
        self.dep = dep
        self.unidades = list(unidades)
        niveles = sorted({u.nivel for u in self.unidades if u.nivel})
        # el nivel mas grueso bajo el departamento se reporta como "municipio",
        # el mas fino (si existe otro) como "distrito"
        self.nivel_municipio = niveles[0] if niveles else None
        self.nivel_distrito = niveles[-1] if len(niveles) > 1 else None
        self._cache: Dict[Tuple[float, float], Tuple[str, str, str]] = {}

    #: tolerancia (grados, ~330 m) para asignar el limite mas cercano cuando el
    #: punto queda justo fuera de todos los poligonos (bordes compartidos,
    #: centroides de vias que cruzan el limite, imprecision del mapeo).
    TOLERANCIA_CERCANIA = 0.003

    def ubicar(self, lat: float, lon: float) -> Tuple[str, str]:
        """Municipio y distrito del punto (cadenas vacias si no se determinan)."""
        municipio, distrito, _ = self.ubicar_detalle(lat, lon)
        return municipio, distrito

    def ubicar_detalle(self, lat: float, lon: float) -> Tuple[str, str, str]:
        """Municipio, distrito y el listado de TODAS las unidades que lo contienen.

        El tercer valor conserva cualquier nivel administrativo adicional que
        exista en OSM (por ejemplo un nivel 7 intermedio), para que no se pierda
        informacion si la division territorial cambia.
        """
        clave = (round(lat, 5), round(lon, 5))
        if clave in self._cache:
            return self._cache[clave]
        municipio = ""
        distrito = ""
        contenedoras: List[Tuple[int, str]] = []
        for unidad in self.unidades:
            if not unidad.contiene(lat, lon):
                continue
            contenedoras.append((unidad.nivel, unidad.nombre))
            if unidad.nivel == self.nivel_municipio and not municipio:
                municipio = unidad.nombre
            elif unidad.nivel == self.nivel_distrito and not distrito:
                distrito = unidad.nombre
            elif not municipio and self.nivel_municipio is None:
                municipio = unidad.nombre
        if not municipio:
            municipio = self._mas_cercano(lat, lon, self.nivel_municipio)
        if not distrito and self.nivel_distrito is not None:
            distrito = self._mas_cercano(lat, lon, self.nivel_distrito)
        detalle = " | ".join("%s (nivel %d)" % (nombre, nivel)
                             for nivel, nombre in sorted(contenedoras))
        resultado = (municipio, distrito, detalle)
        if len(self._cache) < 500000:
            self._cache[clave] = resultado
        return resultado

    def _mas_cercano(self, lat: float, lon: float,
                     nivel: Optional[int]) -> str:
        """Unidad mas cercana del nivel dado, si esta dentro de la tolerancia."""
        if nivel is None:
            return ""
        mejor_nombre = ""
        mejor_distancia = self.TOLERANCIA_CERCANIA
        for unidad in self.unidades:
            if unidad.nivel != nivel:
                continue
            s, w, n, e = unidad.bbox
            if not (s - mejor_distancia <= lat <= n + mejor_distancia
                    and w - mejor_distancia <= lon <= e + mejor_distancia):
                continue
            distancia = unidad.distancia_grados(lat, lon)
            if distancia <= mejor_distancia:
                mejor_distancia = distancia
                mejor_nombre = unidad.nombre
        return mejor_nombre


# --------------------------------------------------------------------------- #
# Consulta de categorias (con division automatica en mosaicos)
# --------------------------------------------------------------------------- #

def construir_consulta(cat: Dict[str, Any], area_id: int,
                       bbox: Optional[Tuple[float, float, float, float]],
                       timeout: int, salida: str = "tags center") -> str:
    """Arma la consulta Overpass QL de una categoria dentro de un area.

    `salida` es lo que se pide a Overpass: "tags center" para los datos o
    "count" para solo contar (sin transferir los elementos).
    """
    filtro_bbox = ""
    if bbox:
        filtro_bbox = "(%.6f,%.6f,%.6f,%.6f)" % bbox  # (sur,oeste,norte,este)
    lineas = ["[out:json][timeout:%d];" % timeout,
              "area(id:%d)->.zona;" % area_id,
              "("]
    for selector in cat["selectores"]:
        lineas.append("  nwr%s(area.zona)%s;" % (selector, filtro_bbox))
    lineas.append(");")
    lineas.append("out %s;" % salida)
    return "\n".join(lineas)


def dividir_bbox(bbox: Tuple[float, float, float, float],
                 n: int) -> List[Tuple[float, float, float, float]]:
    """Parte un bbox (sur,oeste,norte,este) en n x n mosaicos."""
    s, w, norte, e = bbox
    alto = (norte - s) / n
    ancho = (e - w) / n
    mosaicos = []
    for i in range(n):
        for j in range(n):
            mosaicos.append((s + i * alto, w + j * ancho,
                             s + (i + 1) * alto if i < n - 1 else norte,
                             w + (j + 1) * ancho if j < n - 1 else e))
    return mosaicos


def recolectar_categoria(cli: ClienteOverpass, cat: Dict[str, Any], dep: Area,
                         division: Optional[int] = None,
                         profundidad_max: int = 4,
                         silencioso: bool = False) -> Dict[Tuple[str, int], Dict[str, Any]]:
    """Descarga todos los elementos de una categoria dentro de un departamento.

    Si el servidor se satura (timeout / memoria), el mosaico se subdivide en 4 y
    se reintenta, hasta `profundidad_max` niveles.
    """
    division = division if division is not None else int(cat["division_inicial"])
    elementos: Dict[Tuple[str, int], Dict[str, Any]] = {}

    if division <= 1:
        pendientes: List[Tuple[Optional[Tuple[float, float, float, float]], int]] = [(None, 0)]
    else:
        pendientes = [(b, 1) for b in dividir_bbox(dep.bbox, division)]

    total_mosaicos = len(pendientes)
    procesados = 0
    while pendientes:
        bbox, profundidad = pendientes.pop(0)
        ql = construir_consulta(cat, dep.area_overpass, bbox, cli.timeout_consulta)
        etiqueta = "%s / %s%s" % (cat["clave"], dep.nombre,
                                  "" if bbox is None else " mosaico %s" %
                                  ",".join("%.3f" % v for v in bbox))
        try:
            datos = cli.consultar(ql, etiqueta, meta={
                "tipo": "datos", "categoria": cat["clave"],
                "departamento": dep.nombre,
                "bbox": list(bbox) if bbox else None})
        except ErrorSaturacion as exc:
            if profundidad >= profundidad_max:
                log("    !! no se pudo completar %s (%s). Se omite ese mosaico."
                    % (etiqueta, exc), silencioso)
                continue
            base = bbox if bbox is not None else dep.bbox
            nuevos = dividir_bbox(base, 2)
            pendientes = [(b, profundidad + 1) for b in nuevos] + pendientes
            total_mosaicos += len(nuevos)
            log("    -> servidor saturado; se divide en %d mosaicos (nivel %d)"
                % (len(nuevos), profundidad + 1), silencioso)
            continue
        nuevos_elementos = 0
        for el in datos.get("elements", []):
            clave = (el.get("type", ""), int(el.get("id", 0)))
            if clave not in elementos:
                elementos[clave] = el
                nuevos_elementos += 1
        procesados += 1
        log("    %s: +%d elementos (acumulado %d) [%d/%d]"
            % (etiqueta, nuevos_elementos, len(elementos), procesados,
               total_mosaicos), silencioso)
    return elementos


def contar_categoria(cli: ClienteOverpass, cat: Dict[str, Any],
                    dep: Area) -> Optional[Dict[str, int]]:
    """Cuenta (sin descargar) cuantos elementos hay de una categoria en un area.

    Devuelve {"nodes":.., "ways":.., "relations":.., "total":..} o None si el
    servidor no alcanzo a contarlos.
    """
    ql = construir_consulta(cat, dep.area_overpass, None, cli.timeout_consulta,
                            salida="count")
    try:
        datos = cli.consultar(ql, "conteo %s / %s" % (cat["clave"], dep.nombre),
                              meta={"tipo": "conteo", "categoria": cat["clave"],
                                    "departamento": dep.nombre})
    except (ErrorSaturacion, ErrorOverpass):
        return None
    for el in datos.get("elements", []):
        if el.get("type") == "count":
            etiquetas = el.get("tags", {}) or {}
            def _n(clave: str) -> int:
                try:
                    return int(etiquetas.get(clave, 0))
                except (TypeError, ValueError):
                    return 0
            return {"nodes": _n("nodes"), "ways": _n("ways"),
                    "relations": _n("relations"), "total": _n("total")}
    return None


# --------------------------------------------------------------------------- #
# Conversion de elementos OSM a filas
# --------------------------------------------------------------------------- #

def coordenadas(el: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    if el.get("lat") is not None and el.get("lon") is not None:
        return float(el["lat"]), float(el["lon"])
    centro = el.get("center") or {}
    if centro.get("lat") is not None and centro.get("lon") is not None:
        return float(centro["lat"]), float(centro["lon"])
    bounds = el.get("bounds") or {}
    if bounds.get("minlat") is not None:
        return ((float(bounds["minlat"]) + float(bounds["maxlat"])) / 2.0,
                (float(bounds["minlon"]) + float(bounds["maxlon"])) / 2.0)
    return None


def valor_subcategoria(cat: Dict[str, Any], tags: Dict[str, str]) -> str:
    """Deduce el valor de subcategoria segun el orden de llaves de la categoria."""
    for llave in cat["llaves_subcat"]:
        valor = tags.get(llave)
        if valor:
            return valor
    return ""


def primer_valor(tags: Dict[str, str], llaves: Sequence[str]) -> str:
    for llave in llaves:
        valor = tags.get(llave)
        if valor:
            return str(valor)
    return ""


def elemento_a_fila(el: Dict[str, Any], cat: Dict[str, Any], dep_nombre: str,
                    localizador: Optional[Localizador],
                    fecha: str) -> Optional[Dict[str, Any]]:
    punto = coordenadas(el)
    if punto is None:
        return None
    lat, lon = punto
    tags = el.get("tags", {}) or {}
    subcat = valor_subcategoria(cat, tags)

    municipio = distrito = unidades_admin = ""
    if localizador is not None:
        municipio, distrito, unidades_admin = localizador.ubicar_detalle(lat, lon)

    fila: Dict[str, Any] = {
        "categoria": cat["clave"],
        "categoria_es": cat["etiqueta"],
        "grupo": cat["grupo"],
        "subcategoria": subcat,
        "subcategoria_es": etiqueta_subcategoria(cat, subcat),
        "latitud": round(lat, 7),
        "longitud": round(lon, 7),
        "departamento": dep_nombre,
        "municipio": municipio,
        "distrito": distrito,
        "unidades_administrativas": unidades_admin,
        "osm_tipo": el.get("type", ""),
        "osm_id": el.get("id", ""),
        "osm_url": "https://www.openstreetmap.org/%s/%s" % (el.get("type", ""),
                                                            el.get("id", "")),
        "fecha_consulta": fecha,
    }
    for columna, llaves in MAPA_COLUMNAS.items():
        fila[columna] = primer_valor(tags, llaves)

    # direccion compuesta cuando no existe addr:full
    if not fila["direccion"]:
        partes = [p for p in [fila["calle"], fila["numero"],
                              fila["colonia_barrio"], fila["ciudad"]] if p]
        fila["direccion"] = ", ".join(partes)

    for etq in cat["campos_extra"]:
        fila["tag_%s" % etq] = tags.get(etq, "")

    fila["todas_las_etiquetas"] = json.dumps(tags, ensure_ascii=False,
                                             sort_keys=True)
    return fila


def columnas_de_categoria(cat: Dict[str, Any]) -> List[str]:
    return (list(COLUMNAS_BASE)
            + ["tag_%s" % e for e in cat["campos_extra"]]
            + ["todas_las_etiquetas"])


# --------------------------------------------------------------------------- #
# Escritura de resultados (Excel / CSV)
# --------------------------------------------------------------------------- #

ANCHOS_COLUMNA = {
    "categoria": 14, "categoria_es": 24, "grupo": 26, "subcategoria": 22,
    "subcategoria_es": 30, "nombre": 40, "nombre_alterno": 26, "marca": 22,
    "operador": 26, "latitud": 12, "longitud": 12, "departamento": 16,
    "municipio": 22, "distrito": 22, "unidades_administrativas": 38,
    "direccion": 42, "calle": 26,
    "numero": 9, "colonia_barrio": 24, "ciudad": 20, "codigo_postal": 12,
    "telefono": 18, "celular_whatsapp": 18, "correo": 26, "sitio_web": 34,
    "facebook": 26, "horario": 28, "cocina": 18, "deporte": 16, "religion": 16,
    "accesibilidad": 14, "internet": 14, "acepta_tarjeta": 14,
    "niveles_edificio": 10, "capacidad": 10, "wikidata": 14,
    "codigo_referencia": 16, "descripcion": 34, "fuente_osm": 22,
    "osm_tipo": 10, "osm_id": 14, "osm_url": 44, "fecha_consulta": 18,
    "todas_las_etiquetas": 60,
}


def _estilo_encabezado(ws, columnas: Sequence[str], filas_datos: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    relleno = PatternFill("solid", fgColor="1F4E78")
    fuente = Font(color="FFFFFF", bold=True)
    for idx in range(1, len(columnas) + 1):
        celda = ws.cell(row=1, column=idx)
        celda.fill = relleno
        celda.font = fuente
        celda.alignment = Alignment(vertical="center", wrap_text=False)
    ws.freeze_panes = "A2"
    if filas_datos > 0:
        from openpyxl.utils import get_column_letter
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(columnas)),
                                          filas_datos + 1)


def _anchos(ws, columnas: Sequence[str]) -> None:
    from openpyxl.utils import get_column_letter
    for idx, columna in enumerate(columnas, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = ANCHOS_COLUMNA.get(
            columna, max(12, min(30, len(columna) + 4)))


def _hoja_tabla(wb, titulo: str, columnas: Sequence[str],
                filas: Iterable[Sequence[Any]], n_filas: int) -> None:
    ws = wb.create_sheet(titulo[:31])
    ws.append(list(columnas))
    for fila in filas:
        ws.append([_sanear_celda(v) for v in fila])
    _anchos(ws, columnas)
    _estilo_encabezado(ws, columnas, n_filas)


def escribir_excel(ruta: str, filas: List[Dict[str, Any]],
                   columnas: Sequence[str], cat: Dict[str, Any],
                   silencioso: bool = False) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)

    # ---- hoja(s) de datos ----
    bloques = [filas[i:i + MAX_FILAS_HOJA]
               for i in range(0, max(len(filas), 1), MAX_FILAS_HOJA)] or [[]]
    for n, bloque in enumerate(bloques, start=1):
        titulo = "Datos" if len(bloques) == 1 else "Datos_%d" % n
        _hoja_tabla(wb, titulo, columnas,
                    ([f.get(c, "") for c in columnas] for f in bloque),
                    len(bloque))

    # ---- resumen por subcategoria ----
    conteo_sub: Dict[Tuple[str, str], int] = defaultdict(int)
    conteo_mun: Dict[Tuple[str, str, str], int] = defaultdict(int)
    con_nombre = 0
    for f in filas:
        conteo_sub[(f.get("subcategoria", ""), f.get("subcategoria_es", ""))] += 1
        conteo_mun[(f.get("departamento", ""), f.get("municipio", ""),
                    f.get("distrito", ""))] += 1
        if f.get("nombre"):
            con_nombre += 1
    _hoja_tabla(
        wb, "Resumen_subcategoria",
        ["subcategoria", "subcategoria_es", "cantidad"],
        ([k[0], k[1], v] for k, v in sorted(conteo_sub.items(),
                                            key=lambda kv: -kv[1])),
        len(conteo_sub))
    _hoja_tabla(
        wb, "Resumen_territorio",
        ["departamento", "municipio", "distrito", "cantidad"],
        ([k[0], k[1], k[2], v] for k, v in sorted(conteo_mun.items(),
                                                  key=lambda kv: (kv[0][0],
                                                                  kv[0][1],
                                                                  kv[0][2]))),
        len(conteo_mun))

    # ---- ficha tecnica ----
    info = [
        ["Categoria (llave OSM)", cat["clave"]],
        ["Categoria", cat["etiqueta"]],
        ["Grupo tematico", cat["grupo"]],
        ["Filtros Overpass", " ".join(cat["selectores"])],
        ["Registros", len(filas)],
        ["Registros con nombre", con_nombre],
        ["Subcategorias distintas", len(conteo_sub)],
        ["Fecha de extraccion", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["Fuente", "OpenStreetMap (c) colaboradores de OSM - ODbL 1.0"],
        ["Obtenido con", "extraer_osm.py v%s (Overpass API)" % VERSION],
    ]
    _hoja_tabla(wb, "Ficha_tecnica", ["campo", "valor"], info, len(info))

    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    wb.save(ruta)
    log("  -> %s (%d filas)" % (ruta, len(filas)), silencioso)


def escribir_csv(ruta: str, filas: List[Dict[str, Any]],
                 columnas: Sequence[str], silencioso: bool = False) -> None:
    import csv
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=list(columnas),
                                  extrasaction="ignore")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({c: fila.get(c, "") for c in columnas})
    log("  -> %s (%d filas)" % (ruta, len(filas)), silencioso)


def escribir_resumen_general(ruta: str, resumen: List[Dict[str, Any]],
                             departamentos: Sequence[Area],
                             unidades: Dict[str, List[Area]],
                             silencioso: bool = False) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)

    columnas = ["categoria", "categoria_es", "grupo", "registros",
                "con_nombre", "subcategorias", "archivo"]
    _hoja_tabla(wb, "Resumen_categorias", columnas,
                ([r.get(c, "") for c in columnas] for r in resumen),
                len(resumen))

    total_por_cat_mun: Dict[Tuple[str, str, str], int] = defaultdict(int)
    for r in resumen:
        for (dep, mun), cantidad in r.get("por_municipio", {}).items():
            total_por_cat_mun[(r["categoria"], dep, mun)] += cantidad
    filas_mun = [[c, d, m, v] for (c, d, m), v in
                 sorted(total_por_cat_mun.items())]
    _hoja_tabla(wb, "Registros_por_municipio",
                ["categoria", "departamento", "municipio", "registros"],
                filas_mun, len(filas_mun))

    filas_adm: List[List[Any]] = []
    for dep in departamentos:
        filas_adm.append([dep.nombre, dep.nivel, dep.rel_id, "departamento"])
        for unidad in unidades.get(dep.nombre, []):
            filas_adm.append([unidad.nombre, unidad.nivel, unidad.rel_id,
                              "municipio/distrito"])
    _hoja_tabla(wb, "Limites_administrativos",
                ["nombre", "admin_level", "relacion_osm", "tipo"],
                filas_adm, len(filas_adm))

    total = sum(r["registros"] for r in resumen)
    info = [
        ["Total de registros", total],
        ["Categorias procesadas", len(resumen)],
        ["Departamentos", ", ".join(d.nombre for d in departamentos)],
        ["Fecha de extraccion", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")],
        ["Fuente", "OpenStreetMap (c) colaboradores de OSM - ODbL 1.0"],
        ["Atribucion requerida", "(c) OpenStreetMap contributors"],
        ["Herramienta", "extraer_osm.py v%s" % VERSION],
    ]
    _hoja_tabla(wb, "Ficha_tecnica", ["campo", "valor"], info, len(info))
    wb.save(ruta)
    log("-> resumen general: %s" % ruta, silencioso)


# --------------------------------------------------------------------------- #
# Proceso principal
# --------------------------------------------------------------------------- #

def verificar_openpyxl() -> None:
    """Falla de inmediato si falta openpyxl, antes de descargar nada.

    Sin esta comprobacion el script descargaba todo (dejando solo los JSON de la
    cache) y fallaba recien al momento de escribir los Excel.
    """
    try:
        import openpyxl
        _ = openpyxl.__version__
    except ImportError:
        raise ErrorDependencia(
            "falta la libreria 'openpyxl', necesaria para escribir los archivos "
            "Excel.\n"
            "  Instalela con:  pip install openpyxl\n"
            "               o:  python -m pip install -r requirements.txt\n"
            "  (si solo quiere archivos de texto, use --formato csv)")


def informar_resultado(resumen: Sequence[Dict[str, Any]],
                       args: argparse.Namespace) -> None:
    """Imprime el resumen final y donde quedaron los archivos generados."""
    total = sum(r["registros"] for r in resumen)
    carpeta = os.path.abspath(args.salida)
    print("")
    print("Resumen por categoria")
    print("-" * 66)
    for r in resumen:
        print("  %-18s %-34s %8d" % (r["categoria"], r["categoria_es"][:34],
                                     r["registros"]))
    print("-" * 66)
    print("  %-53s %8d" % ("TOTAL", total))
    print("")
    extensiones = (".xlsx", ".csv") if args.formato == "ambos" else (
        (".csv",) if args.formato == "csv" else (".xlsx",))
    generados = sorted(f for f in os.listdir(carpeta)
                       if f.endswith(extensiones)) if os.path.isdir(carpeta) else []
    print("ARCHIVOS GENERADOS en %s (%d):" % (carpeta, len(generados)))
    for nombre in generados:
        tamano = os.path.getsize(os.path.join(carpeta, nombre)) / 1024.0
        print("   %-46s %8.0f KB" % (nombre, tamano))
    print("")
    if not args.sin_cache:
        print("Nota: los archivos .json de %s son la cache de las respuestas de "
              "Overpass," % os.path.abspath(args.cache))
        print("      no el resultado. Los datos finales son los .xlsx de arriba.")
    print("Datos (c) colaboradores de OpenStreetMap, licencia ODbL 1.0.")


def crear_cliente(args: argparse.Namespace) -> ClienteOverpass:
    """Cliente Overpass configurado con las opciones de la linea de comandos."""
    endpoints = ENDPOINTS_OVERPASS
    if args.endpoint:
        endpoints = [args.endpoint] + [e for e in ENDPOINTS_OVERPASS
                                       if e != args.endpoint]
    return ClienteOverpass(
        endpoints=endpoints,
        dir_cache=None if args.sin_cache else args.cache,
        pausa=args.pausa,
        timeout_consulta=args.timeout,
        timeout_http=args.timeout + 300,
        max_reintentos=args.reintentos,
        silencioso=args.silencioso,
    )


def ejecutar(args: argparse.Namespace) -> int:
    silencioso = args.silencioso
    fecha = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    if args.formato in ("excel", "ambos"):
        verificar_openpyxl()

    claves = args.categorias or list(CATEGORIAS.keys())
    desconocidas = [c for c in claves if c not in CATEGORIAS]
    if desconocidas:
        print("Categorias desconocidas: %s\nUse --listar-categorias para ver las "
              "disponibles." % ", ".join(desconocidas), file=sys.stderr)
        return 2

    cli = crear_cliente(args)

    log("extraer_osm v%s | shapely: %s" % (VERSION, "si" if HAY_SHAPELY else "no"),
        silencioso)
    log("categorias a procesar (%d): %s" % (len(claves), ", ".join(claves)),
        silencioso)
    log("departamentos: %s" % ", ".join(args.departamentos), silencioso)

    # 1) limites administrativos
    log("1/3 descargando limites administrativos...", silencioso)
    departamentos = obtener_departamentos(cli, args.departamentos)
    unidades: Dict[str, List[Area]] = {}
    localizadores: Dict[str, Optional[Localizador]] = {}
    for dep in departamentos:
        if args.sin_admin:
            unidades[dep.nombre] = []
            localizadores[dep.nombre] = None
            continue
        internas = obtener_unidades_internas(cli, dep)
        unidades[dep.nombre] = internas
        localizadores[dep.nombre] = Localizador(dep, internas)
        niveles = sorted({u.nivel for u in internas})
        log("  %s: %d unidades internas (admin_level %s)"
            % (dep.nombre, len(internas),
               ", ".join(str(n) for n in niveles) or "-"), silencioso)

    # 2) consulta y escritura por categoria
    deps_por_nombre = {d.nombre: d for d in departamentos}

    log("2/3 consultando categorias en Overpass...", silencioso)
    os.makedirs(args.salida, exist_ok=True)
    resumen: List[Dict[str, Any]] = []
    for n, clave in enumerate(claves, start=1):
        cat = CATEGORIAS[clave]
        log("[%d/%d] %s (%s)" % (n, len(claves), cat["etiqueta"], clave), silencioso)
        # Un elemento puede aparecer en las consultas de los dos departamentos
        # (vias o poligonos que cruzan el limite, nodos sobre la linea divisoria):
        # se guarda una sola vez, en el departamento que contiene su punto.
        filas_por_elemento: "OrderedDict[Tuple[str, Any], Dict[str, Any]]" = OrderedDict()
        sin_coordenadas = 0
        repetidos = 0
        for dep in departamentos:
            elementos = recolectar_categoria(
                cli, cat, dep,
                division=args.division or None,
                silencioso=silencioso)
            for el in elementos.values():
                fila = elemento_a_fila(el, cat, dep.nombre,
                                       localizadores.get(dep.nombre), fecha)
                if fila is None:
                    sin_coordenadas += 1
                    continue
                clave_el = (el.get("type", ""), el.get("id"))
                previa = filas_por_elemento.get(clave_el)
                if previa is None:
                    filas_por_elemento[clave_el] = fila
                    continue
                repetidos += 1
                dep_previa = deps_por_nombre.get(previa["departamento"])
                encaja_ahora = dep.contiene(fila["latitud"], fila["longitud"])
                encajaba_antes = (dep_previa is not None and dep_previa.contiene(
                    previa["latitud"], previa["longitud"]))
                if encaja_ahora and not encajaba_antes:
                    filas_por_elemento[clave_el] = fila
        filas = list(filas_por_elemento.values())
        por_municipio: Dict[Tuple[str, str], int] = defaultdict(int)
        for f in filas:
            por_municipio[(f["departamento"], f["municipio"])] += 1
        if sin_coordenadas:
            log("  (%d elementos sin coordenadas omitidos)" % sin_coordenadas,
                silencioso)
        if repetidos:
            log("  (%d elementos compartidos entre departamentos, contados una vez)"
                % repetidos, silencioso)

        columnas = columnas_de_categoria(cat)
        base = os.path.join(args.salida, cat["archivo"])
        if args.formato in ("excel", "ambos"):
            escribir_excel(base + ".xlsx", filas, columnas, cat, silencioso)
        if args.formato in ("csv", "ambos"):
            escribir_csv(base + ".csv", filas, columnas, silencioso)

        resumen.append({
            "categoria": clave,
            "categoria_es": cat["etiqueta"],
            "grupo": cat["grupo"],
            "registros": len(filas),
            "con_nombre": sum(1 for f in filas if f.get("nombre")),
            "subcategorias": len({f.get("subcategoria", "") for f in filas}),
            "archivo": os.path.basename(base) + (
                ".xlsx" if args.formato != "csv" else ".csv"),
            "por_municipio": dict(por_municipio),
        })

    # 3) resumen general
    log("3/3 escribiendo resumen general...", silencioso)
    escribir_resumen_general(os.path.join(args.salida, "00_RESUMEN_GENERAL.xlsx"),
                             resumen, departamentos, unidades, silencioso)

    log("LISTO | consultas: %d (cache: %d) | descargado: %.1f MB"
        % (cli.consultas_realizadas, cli.consultas_en_cache,
           cli.bytes_descargados / 1048576.0), silencioso)
    informar_resultado(resumen, args)
    return 0


# --------------------------------------------------------------------------- #
# Reconstruccion de los Excel a partir de la cache (sin red)
# --------------------------------------------------------------------------- #

#: llaves OSM que identifican a cada categoria (para clasificar cache sin metadatos)
LLAVES_DE_CATEGORIA: Dict[str, List[str]] = {
    clave: list(dict.fromkeys(cat["llaves_subcat"] + [cat["llave"]]))
    for clave, cat in CATEGORIAS.items()
}


def _condiciones_de_selector(selector: str) -> List[Tuple[str, Optional[str]]]:
    """'["highway"="bus_stop"]' -> [("highway", "bus_stop")]; '["shop"]' -> [("shop", None)]."""
    return [(llave, valor if valor else None) for llave, valor in
            re.findall(r'\["([^"]+)"(?:="([^"]*)")?\]', selector)]


#: condiciones de cada categoria: lista de selectores, cada uno con sus condiciones
CONDICIONES_DE_CATEGORIA: Dict[str, List[List[Tuple[str, Optional[str]]]]] = {
    clave: [_condiciones_de_selector(s) for s in cat["selectores"]]
    for clave, cat in CATEGORIAS.items()
}


def _elemento_es_de_categoria(tags: Dict[str, str], clave: str) -> bool:
    """True si las etiquetas satisfacen alguno de los selectores de la categoria."""
    for condiciones in CONDICIONES_DE_CATEGORIA[clave]:
        if condiciones and all(
                (llave in tags) if valor is None else (tags.get(llave) == valor)
                for llave, valor in condiciones):
            return True
    return False


def _es_respuesta_de_limites(elementos: Sequence[Dict[str, Any]]) -> bool:
    """True si la respuesta son relaciones de limites administrativos."""
    relaciones = [e for e in elementos if e.get("type") == "relation"
                  and e.get("members")]
    if not relaciones or len(relaciones) < len(elementos) / 2:
        return False
    return any((e.get("tags") or {}).get("boundary") == "administrative"
               for e in relaciones)


def inferir_categoria(elementos: Sequence[Dict[str, Any]],
                      frecuencia_llaves: Optional[Dict[str, int]] = None
                      ) -> Optional[str]:
    """Deduce a que categoria pertenece una respuesta guardada sin metadatos.

    Toma las llaves OSM presentes en TODOS los elementos (la consulta filtro por
    una de ellas) y, si hay varias candidatas, se queda con la menos frecuente en
    el conjunto de la cache: la mas especifica (por ejemplo `cuisine` antes que
    `amenity`).
    """
    if not elementos:
        return None
    # cobertura: que fraccion de los elementos encaja en los selectores de cada
    # categoria. La consulta pidio una categoria, asi que esa los cubre a todos
    # (una categoria como public_transport mezcla varias llaves: highway=bus_stop,
    # public_transport=*, amenity=bus_station).
    coincidencias: Dict[str, int] = defaultdict(int)
    llaves_vistas: Dict[str, set] = defaultdict(set)
    for el in elementos:
        tags = el.get("tags") or {}
        for clave in CATEGORIAS:
            if _elemento_es_de_categoria(tags, clave):
                coincidencias[clave] += 1
                llaves_vistas[clave].update(
                    ll for ll in LLAVES_DE_CATEGORIA[clave] if ll in tags)
    total = len(elementos)
    if not coincidencias:
        return None
    # se queda con la categoria que cubre mas elementos (normalmente todos, porque
    # la consulta filtro por ella); si no cubre ni la mitad, no se arriesga
    mejor = max(coincidencias.values())
    if mejor < max(1, total // 2):
        return None
    candidatas = [c for c, n in coincidencias.items() if n == mejor]
    if len(candidatas) == 1:
        return candidatas[0]

    def rareza(clave: str) -> Tuple[int, int]:
        llaves = llaves_vistas.get(clave) or set(LLAVES_DE_CATEGORIA[clave])
        total_llave = min((frecuencia_llaves or {}).get(ll, 0) for ll in llaves) \
            if frecuencia_llaves else 0
        return (total_llave, list(CATEGORIAS).index(clave))

    return sorted(candidatas, key=rareza)[0]


def leer_cache(dir_cache: str, silencioso: bool = False
               ) -> Tuple[List[Area], List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]]:
    """Lee la cache: devuelve (areas administrativas, respuestas de datos)."""
    import glob as _glob
    archivos = sorted(_glob.glob(os.path.join(dir_cache, "*.json")))
    if not archivos:
        raise ErrorOverpass(
            "no hay archivos JSON en la cache '%s'. Corra primero la extraccion "
            "(sin --sin-cache) o indique la carpeta con --cache." % dir_cache)
    log("leyendo %d archivos de cache en %s" % (len(archivos), dir_cache), silencioso)

    areas: List[Area] = []
    respuestas: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
    frecuencia: Dict[str, int] = defaultdict(int)
    ilegibles = 0
    for archivo in archivos:
        try:
            with open(archivo, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
        except (ValueError, OSError):
            ilegibles += 1
            continue
        elementos = datos.get("elements") or []
        if not elementos:
            continue
        meta = dict(datos.get("_extraer_osm") or {})
        meta["archivo"] = os.path.basename(archivo)
        tipo = meta.get("tipo")
        if tipo == "conteo" or any(e.get("type") == "count" for e in elementos):
            continue
        if tipo in ("limites", "pais") or (tipo is None
                                           and _es_respuesta_de_limites(elementos)):
            for el in elementos:
                if el.get("type") != "relation":
                    continue
                area = area_desde_relacion(el)
                if area is not None:
                    areas.append(area)
            continue
        for el in elementos:
            for llave in (el.get("tags") or {}):
                frecuencia[llave] += 1
        respuestas.append((meta, elementos))
    if ilegibles:
        log("  (%d archivos de cache ilegibles, omitidos)" % ilegibles, silencioso)

    # clasificar las respuestas que no traen metadatos
    for meta, elementos in respuestas:
        if not meta.get("categoria"):
            meta["categoria"] = inferir_categoria(elementos, frecuencia)
            meta["categoria_inferida"] = True
    return areas, respuestas


def reconstruir_desde_cache(args: argparse.Namespace) -> int:
    """Genera los Excel con los datos ya descargados en la cache, sin red."""
    silencioso = args.silencioso
    if args.formato in ("excel", "ambos"):
        verificar_openpyxl()
    fecha = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    areas, respuestas = leer_cache(args.cache, silencioso)

    # --- limites: departamentos (nivel 4) y unidades internas (5..9) ---
    unicas: Dict[int, Area] = {}
    for area in areas:
        unicas.setdefault(area.rel_id, area)
    departamentos = [a for a in unicas.values() if a.nivel == 4]
    if args.departamentos:
        buscados = [normalizar(n) for n in args.departamentos]
        filtrados = [d for d in departamentos
                     if any(b == normalizar(d.nombre) or b in normalizar(d.nombre)
                            or normalizar(d.nombre) in b for b in buscados)]
        if filtrados:
            departamentos = filtrados
    internas = [a for a in unicas.values() if 5 <= a.nivel <= 9]
    localizadores: Dict[str, Localizador] = {}
    for dep in departamentos:
        propias = [u for u in internas
                   if dep.contiene((u.bbox[0] + u.bbox[2]) / 2.0,
                                   (u.bbox[1] + u.bbox[3]) / 2.0)]
        localizadores[dep.nombre] = Localizador(dep, propias)
        log("  %s: %d unidades internas" % (dep.nombre, len(propias)), silencioso)
    if not departamentos:
        log("  (!) la cache no trae limites administrativos: las columnas "
            "departamento, municipio y distrito quedaran vacias", silencioso)

    def ubicar_departamento(lat: float, lon: float, sugerido: str) -> str:
        if sugerido:
            dep = next((d for d in departamentos if d.nombre == sugerido), None)
            if dep is not None and dep.contiene(lat, lon):
                return sugerido
        for dep in departamentos:
            if dep.contiene(lat, lon):
                return dep.nombre
        return sugerido

    # --- agrupar los elementos por categoria ---
    por_categoria: "OrderedDict[str, OrderedDict[Tuple[str, Any], Dict[str, Any]]]" = \
        OrderedDict((c, OrderedDict()) for c in CATEGORIAS)
    sin_clasificar = 0
    sin_coordenadas = 0
    inferidas: Dict[str, int] = defaultdict(int)
    for meta, elementos in respuestas:
        clave = meta.get("categoria")
        if clave not in CATEGORIAS:
            sin_clasificar += len(elementos)
            continue
        if meta.get("categoria_inferida"):
            inferidas[clave] += 1
        if args.categorias and clave not in args.categorias:
            continue
        cat = CATEGORIAS[clave]
        for el in elementos:
            punto = coordenadas(el)
            if punto is None:
                sin_coordenadas += 1
                continue
            nombre_dep = ubicar_departamento(punto[0], punto[1],
                                             meta.get("departamento", ""))
            fila = elemento_a_fila(el, cat, nombre_dep,
                                   localizadores.get(nombre_dep), fecha)
            if fila is None:
                sin_coordenadas += 1
                continue
            por_categoria[clave][(el.get("type", ""), el.get("id"))] = fila

    if inferidas:
        log("  categorias deducidas de la cache antigua (sin metadatos): %s"
            % ", ".join("%s (%d respuestas)" % (k, v)
                        for k, v in sorted(inferidas.items())), silencioso)
    if sin_clasificar:
        log("  (%d elementos en respuestas que no se pudieron clasificar)"
            % sin_clasificar, silencioso)
    if sin_coordenadas:
        log("  (%d elementos sin coordenadas omitidos)" % sin_coordenadas, silencioso)

    # --- escribir un archivo por categoria con datos ---
    os.makedirs(args.salida, exist_ok=True)
    resumen: List[Dict[str, Any]] = []
    for clave, filas_dict in por_categoria.items():
        if not filas_dict:
            continue
        cat = CATEGORIAS[clave]
        filas = list(filas_dict.values())
        columnas = columnas_de_categoria(cat)
        base = os.path.join(args.salida, cat["archivo"])
        if args.formato in ("excel", "ambos"):
            escribir_excel(base + ".xlsx", filas, columnas, cat, silencioso)
        if args.formato in ("csv", "ambos"):
            escribir_csv(base + ".csv", filas, columnas, silencioso)
        por_municipio: Dict[Tuple[str, str], int] = defaultdict(int)
        for f in filas:
            por_municipio[(f["departamento"], f["municipio"])] += 1
        resumen.append({
            "categoria": clave,
            "categoria_es": cat["etiqueta"],
            "grupo": cat["grupo"],
            "registros": len(filas),
            "con_nombre": sum(1 for f in filas if f.get("nombre")),
            "subcategorias": len({f.get("subcategoria", "") for f in filas}),
            "archivo": os.path.basename(base) + (
                ".xlsx" if args.formato != "csv" else ".csv"),
            "por_municipio": dict(por_municipio),
        })

    if not resumen:
        print("\nLa cache no contenia datos utilizables. Corra la extraccion "
              "normal:\n  python extraer_osm.py", file=sys.stderr)
        return 1
    if args.formato in ("excel", "ambos"):
        escribir_resumen_general(
            os.path.join(args.salida, "00_RESUMEN_GENERAL.xlsx"),
            resumen, departamentos,
            {d.nombre: localizadores[d.nombre].unidades for d in departamentos},
            silencioso)
    informar_resultado(resumen, args)
    return 0


def diagnostico(cli: ClienteOverpass, claves: Sequence[str],
                nombres_departamentos: Sequence[str],
                silencioso: bool = False) -> int:
    """Revisa servidor, limites administrativos y cuanta informacion hay.

    No descarga los datos: usa `out count`, asi que sirve para saber de antemano
    cuantos registros traera cada categoria y cuanto durara la extraccion.
    """
    print("DIAGNOSTICO extraer_osm v%s" % VERSION)
    print("=" * 78)
    print("Servidores Overpass: %s" % ", ".join(
        urllib.parse.urlsplit(e).netloc for e in cli.endpoints))
    print("shapely instalada: %s" % ("si" if HAY_SHAPELY else "no (se usa el "
                                     "algoritmo interno)"))
    print("")

    print("1) Limites administrativos")
    departamentos = obtener_departamentos(cli, nombres_departamentos)
    if cli.marca_datos_osm:
        print("   datos de OSM actualizados al: %s" % cli.marca_datos_osm)
    unidades: Dict[str, List[Area]] = {}
    for dep in departamentos:
        internas = obtener_unidades_internas(cli, dep)
        unidades[dep.nombre] = internas
        por_nivel: Dict[int, List[str]] = defaultdict(list)
        for unidad in internas:
            por_nivel[unidad.nivel].append(unidad.nombre)
        s, w, n, e = dep.bbox
        print("   %s (relacion %d) bbox %.3f,%.3f,%.3f,%.3f"
              % (dep.nombre, dep.rel_id, s, w, n, e))
        for nivel in sorted(por_nivel):
            nombres = sorted(por_nivel[nivel])
            print("      admin_level %d: %d %s -> %s"
                  % (nivel, len(nombres),
                     "unidad" if len(nombres) == 1 else "unidades",
                     ", ".join(nombres[:6])
                     + (", ..." if len(nombres) > 6 else "")))
        if not internas:
            print("      (!) sin unidades internas: las columnas municipio y "
                  "distrito quedarian vacias")
        loc = Localizador(dep, internas)
        print("      se reportara: municipio = admin_level %s, distrito = "
              "admin_level %s"
              % (loc.nivel_municipio if loc.nivel_municipio else "-",
                 loc.nivel_distrito if loc.nivel_distrito else "-"))
    print("")

    print("2) Cantidad de elementos por categoria (consulta `out count`)")
    encabezado = "   %-18s %12s %12s %12s" % ("categoria", "", "", "")
    print("   %-18s %10s %10s %10s %10s" % ("categoria", "nodos", "vias",
                                            "relaciones", "TOTAL"))
    print("   " + "-" * 62)
    del encabezado
    gran_total = 0
    sin_contar: List[str] = []
    for clave in claves:
        cat = CATEGORIAS[clave]
        suma = {"nodes": 0, "ways": 0, "relations": 0, "total": 0}
        completo = True
        for dep in departamentos:
            conteo = contar_categoria(cli, cat, dep)
            if conteo is None:
                completo = False
                continue
            for k in suma:
                suma[k] += conteo[k]
        if not completo:
            sin_contar.append(clave)
        print("   %-18s %10d %10d %10d %10d%s"
              % (clave, suma["nodes"], suma["ways"], suma["relations"],
                 suma["total"], "" if completo else "  (parcial)"))
        gran_total += suma["total"]
    print("   " + "-" * 62)
    print("   %-18s %43d" % ("TOTAL", gran_total))
    print("")
    if sin_contar:
        print("   (!) No se pudo contar completo: %s. Son las categorias mas "
              "grandes;\n       el script las divide en mosaicos al extraerlas."
              % ", ".join(sin_contar))
    minutos = max(1, int(gran_total / 12000.0) + 2 * len(claves))
    print("3) Estimacion")
    print("   registros esperados: ~%d" % gran_total)
    print("   duracion aproximada: ~%d minutos (%.1f horas), segun la carga del "
          "servidor" % (minutos, minutos / 60.0))
    print("   espacio en disco: ~%.0f MB de cache + ~%.0f MB de Excel"
          % (gran_total * 0.0004, gran_total * 0.0003))
    print("")
    if cli.marca_datos_osm:
        print("Datos de OSM actualizados al %s | (c) colaboradores de "
              "OpenStreetMap (ODbL 1.0)" % cli.marca_datos_osm)
    print("Para extraer: python extraer_osm.py %s"
          % ("" if len(claves) == len(CATEGORIAS)
             else "--categorias " + " ".join(claves)))
    return 0


# --------------------------------------------------------------------------- #
# Autoprueba (no requiere red): valida geometria, consultas y escritura
# --------------------------------------------------------------------------- #

def autoprueba(dir_salida: str) -> int:
    print("== autoprueba de extraer_osm v%s ==" % VERSION)
    fallos = 0

    def check(nombre: str, condicion: bool, detalle: str = "") -> None:
        nonlocal fallos
        print("  [%s] %s%s" % ("ok" if condicion else "FALLA", nombre,
                               "" if condicion or not detalle else " -> " + detalle))
        if not condicion:
            fallos += 1

    # --- catalogo ---
    check("categorias registradas (21)", len(CATEGORIAS) == 21, str(len(CATEGORIAS)))
    total_subcats = sum(len(c["valores"]) for c in CATEGORIAS.values())
    check("subcategorias traducidas > 900", total_subcats > 900, str(total_subcats))
    check("shop con mas de 150 subcategorias",
          len(VALORES_SHOP) >= 150, str(len(VALORES_SHOP)))
    check("archivos de salida unicos",
          len({c["archivo"] for c in CATEGORIAS.values()}) == len(CATEGORIAS))

    # --- consulta Overpass ---
    ql = construir_consulta(CATEGORIAS["public_transport"], 3600001234,
                            (13.6, -89.3, 13.8, -89.1), 600)
    check("consulta con area, selectores multiples y bbox",
          "area(id:3600001234)->.zona;" in ql
          and 'nwr["highway"="bus_stop"](area.zona)(13.600000,-89.300000,'
              '13.800000,-89.100000);' in ql
          and ql.rstrip().endswith("out tags center;"), ql)

    ql_conteo = construir_consulta(CATEGORIAS["amenity"], 3600001234, None, 600,
                                   salida="count")
    check("consulta de conteo sin bbox",
          ql_conteo.rstrip().endswith("out count;")
          and 'nwr["amenity"](area.zona);' in ql_conteo, ql_conteo)

    class _ClienteFalso(ClienteOverpass):
        def __init__(self, respuesta):
            super().__init__(dir_cache=None, pausa=0, silencioso=True)
            self.respuesta = respuesta

        def consultar(self, ql, descripcion="", meta=None):
            if isinstance(self.respuesta, Exception):
                raise self.respuesta
            return self.respuesta

    dep_falso = Area("Depto", 4, 55, [[(13.0, -89.5), (13.0, -89.0),
                                       (13.5, -89.0), (13.5, -89.5),
                                       (13.0, -89.5)]])
    conteo = contar_categoria(
        _ClienteFalso({"elements": [{"type": "count", "id": 0, "tags": {
            "nodes": "120", "ways": "34", "relations": "2", "total": "156"}}]}),
        CATEGORIAS["shop"], dep_falso)
    check("lectura del conteo de Overpass",
          conteo == {"nodes": 120, "ways": 34, "relations": 2, "total": 156},
          str(conteo))
    check("conteo devuelve None si el servidor se satura",
          contar_categoria(_ClienteFalso(ErrorSaturacion("timeout")),
                           CATEGORIAS["building"], dep_falso) is None)

    # --- mosaicos ---
    mosaicos = dividir_bbox((13.0, -89.5, 14.0, -88.5), 2)
    check("division en 2x2 mosaicos", len(mosaicos) == 4)
    check("los mosaicos cubren el bbox completo",
          math.isclose(min(m[0] for m in mosaicos), 13.0)
          and math.isclose(max(m[2] for m in mosaicos), 14.0)
          and math.isclose(min(m[1] for m in mosaicos), -89.5)
          and math.isclose(max(m[3] for m in mosaicos), -88.5))

    # --- geometria: relacion partida en tramos + hueco ---
    relacion = {
        "type": "relation", "id": 999,
        "tags": {"name": "Municipio Prueba", "admin_level": "6",
                 "boundary": "administrative"},
        "members": [
            {"type": "way", "role": "outer", "geometry": [
                {"lat": 13.0, "lon": -89.5}, {"lat": 13.0, "lon": -89.0}]},
            {"type": "way", "role": "outer", "geometry": [
                {"lat": 13.0, "lon": -89.0}, {"lat": 13.5, "lon": -89.0}]},
            {"type": "way", "role": "outer", "geometry": [
                {"lat": 13.5, "lon": -89.0}, {"lat": 13.5, "lon": -89.5}]},
            {"type": "way", "role": "outer", "geometry": [
                {"lat": 13.5, "lon": -89.5}, {"lat": 13.0, "lon": -89.5}]},
            {"type": "way", "role": "inner", "geometry": [
                {"lat": 13.2, "lon": -89.3}, {"lat": 13.2, "lon": -89.2},
                {"lat": 13.3, "lon": -89.2}, {"lat": 13.3, "lon": -89.3},
                {"lat": 13.2, "lon": -89.3}]},
        ],
    }
    area = area_desde_relacion(relacion)
    check("armado de poligono desde tramos sueltos", area is not None)
    if area is not None:
        check("nombre y nivel del area",
              area.nombre == "Municipio Prueba" and area.nivel == 6)
        check("id de area Overpass", area.area_overpass == 3600000999)
        check("punto interior detectado", area.contiene(13.1, -89.4))
        check("punto exterior descartado", not area.contiene(14.0, -89.4))
        check("punto en el hueco descartado", not area.contiene(13.25, -89.25))
        # comparacion con el algoritmo interno (sin shapely)
        area._preparado = None
        check("point-in-polygon interno coincide",
              area.contiene(13.1, -89.4) and not area.contiene(13.25, -89.25)
              and not area.contiene(14.0, -89.4))

    # --- localizador ---
    dep = Area("Departamento Prueba", 4, 1,
               [[(13.0, -89.5), (13.0, -89.0), (13.5, -89.0), (13.5, -89.5),
                 (13.0, -89.5)]])
    muni = Area("Municipio A", 6, 2,
                [[(13.0, -89.5), (13.0, -89.25), (13.5, -89.25), (13.5, -89.5),
                  (13.0, -89.5)]])
    distrito = Area("Distrito A1", 8, 3,
                    [[(13.0, -89.5), (13.0, -89.4), (13.2, -89.4), (13.2, -89.5),
                      (13.0, -89.5)]])
    loc = Localizador(dep, [muni, distrito])
    check("localizador: municipio y distrito",
          loc.ubicar(13.1, -89.45) == ("Municipio A", "Distrito A1"),
          str(loc.ubicar(13.1, -89.45)))
    check("localizador: solo municipio",
          loc.ubicar(13.4, -89.3) == ("Municipio A", ""),
          str(loc.ubicar(13.4, -89.3)))
    check("localizador: punto exactamente sobre el limite",
          loc.ubicar(13.1, -89.25) == ("Municipio A", ""),
          str(loc.ubicar(13.1, -89.25)))
    check("localizador: punto a ~100 m fuera se asigna al mas cercano",
          loc.ubicar(13.1, -89.2491) == ("Municipio A", ""),
          str(loc.ubicar(13.1, -89.2491)))
    check("localizador: punto lejano queda sin municipio",
          loc.ubicar(13.1, -89.1) == ("", ""), str(loc.ubicar(13.1, -89.1)))
    check("distancia al area: dentro = 0",
          math.isclose(muni.distancia_grados(13.1, -89.4), 0.0, abs_tol=1e-9))
    check("distancia al area: fuera > 0",
          muni.distancia_grados(13.1, -89.10) > 0.1,
          str(muni.distancia_grados(13.1, -89.10)))
    sin_shapely = Area("Sin shapely", 6, 9,
                       [[(13.0, -89.5), (13.0, -89.25), (13.5, -89.25),
                         (13.5, -89.5), (13.0, -89.5)]])
    sin_shapely._preparado = None
    check("borde detectado tambien sin shapely",
          sin_shapely.contiene(13.1, -89.25)
          and math.isclose(sin_shapely.distancia_grados(13.1, -89.25), 0.0,
                           abs_tol=1e-6)
          and sin_shapely.distancia_grados(13.1, -89.20) > 0.04)

    check("columna de unidades administrativas presente",
          "unidades_administrativas" in COLUMNAS_BASE)
    check("detalle con todos los niveles administrativos",
          loc.ubicar_detalle(13.1, -89.45)[2]
          == "Municipio A (nivel 6) | Distrito A1 (nivel 8)",
          loc.ubicar_detalle(13.1, -89.45)[2])

    # --- conversion de elementos ---
    fecha = "2026-01-01 00:00"
    nodo = {
        "type": "node", "id": 111, "lat": 13.1, "lon": -89.45,
        "tags": {"shop": "supermarket", "name": "Super Selectos Prueba",
                 "brand": "Super Selectos", "addr:street": "Calle Real",
                 "addr:housenumber": "12", "phone": "+503 2222 2222",
                 "opening_hours": "Mo-Su 07:00-20:00", "wheelchair": "yes"},
    }
    fila = elemento_a_fila(nodo, CATEGORIAS["shop"], "San Salvador", loc, fecha)
    check("fila de nodo shop", fila is not None)
    if fila is not None:
        check("subcategoria traducida",
              fila["subcategoria"] == "supermarket"
              and fila["subcategoria_es"] == "Supermercado")
        check("nombre, marca, telefono y horario",
              fila["nombre"] == "Super Selectos Prueba"
              and fila["marca"] == "Super Selectos"
              and fila["telefono"] == "+503 2222 2222"
              and fila["horario"] == "Mo-Su 07:00-20:00")
        check("direccion compuesta", fila["direccion"] == "Calle Real, 12")
        check("territorio asignado",
              fila["departamento"] == "San Salvador"
              and fila["municipio"] == "Municipio A"
              and fila["distrito"] == "Distrito A1")
        check("url y coordenadas",
              fila["osm_url"] == "https://www.openstreetmap.org/node/111"
              and fila["latitud"] == 13.1 and fila["longitud"] == -89.45)
        check("todas las etiquetas en JSON",
              json.loads(fila["todas_las_etiquetas"])["shop"] == "supermarket")
        check("niveles administrativos en la fila",
              fila["unidades_administrativas"]
              == "Municipio A (nivel 6) | Distrito A1 (nivel 8)",
              fila["unidades_administrativas"])

    via = {"type": "way", "id": 222, "center": {"lat": 13.05, "lon": -89.45},
           "tags": {"highway": "bus_stop", "name": "Parada Centro"}}
    fila_pt = elemento_a_fila(via, CATEGORIAS["public_transport"],
                              "San Salvador", loc, fecha)
    check("way con center y subcategoria por llave alterna",
          fila_pt is not None and fila_pt["subcategoria"] == "bus_stop"
          and fila_pt["subcategoria_es"] == "Parada de bus")
    check("elemento sin coordenadas se descarta",
          elemento_a_fila({"type": "relation", "id": 3, "tags": {"shop": "mall"}},
                          CATEGORIAS["shop"], "San Salvador", loc, fecha) is None)
    check("valor OSM sin traduccion queda legible",
          etiqueta_subcategoria(CATEGORIAS["shop"], "valor_inexistente_raro")
          == "Valor inexistente raro")
    check("valores multiples separados por ;",
          etiqueta_subcategoria(CATEGORIAS["cuisine"], "pizza;burger")
          == "Pizza / Hamburguesas")

    # --- clasificacion de la cache (para --solo-excel) ---
    check("deduce la categoria shop de una respuesta guardada",
          inferir_categoria([{"type": "node", "tags": {"shop": "bakery"}},
                             {"type": "node", "tags": {"shop": "mall",
                                                       "name": "X"}}]) == "shop")
    check("deduce public_transport aunque mezcle highway y public_transport",
          inferir_categoria([
              {"type": "node", "tags": {"highway": "bus_stop", "name": "P1"}},
              {"type": "node", "tags": {"public_transport": "station"}},
              {"type": "way", "tags": {"amenity": "bus_station"}}])
          == "public_transport")
    check("prefiere la llave mas especifica (cuisine sobre amenity)",
          inferir_categoria(
              [{"type": "node", "tags": {"amenity": "restaurant",
                                         "cuisine": "pupusa"}},
               {"type": "node", "tags": {"amenity": "fast_food",
                                         "cuisine": "pizza"}}],
              {"amenity": 5000, "cuisine": 300}) == "cuisine")
    check("no adivina si nada encaja",
          inferir_categoria([{"type": "node", "tags": {"name": "solo nombre"}}])
          is None)
    check("reconoce las respuestas de limites administrativos",
          _es_respuesta_de_limites([relacion])
          and not _es_respuesta_de_limites([nodo]))
    check("verificar_openpyxl no falla cuando esta instalada",
          verificar_openpyxl() is None)

    # --- escritura de archivos ---
    os.makedirs(dir_salida, exist_ok=True)
    cat = CATEGORIAS["shop"]
    columnas = columnas_de_categoria(cat)
    filas = [fila] * 3 if fila else []
    ruta_xlsx = os.path.join(dir_salida, "prueba_shop.xlsx")
    ruta_csv = os.path.join(dir_salida, "prueba_shop.csv")
    try:
        escribir_excel(ruta_xlsx, filas, columnas, cat, silencioso=True)
        escribir_csv(ruta_csv, filas, columnas, silencioso=True)
        from openpyxl import load_workbook
        wb = load_workbook(ruta_xlsx)
        check("hojas del Excel",
              wb.sheetnames == ["Datos", "Resumen_subcategoria",
                                "Resumen_territorio", "Ficha_tecnica"],
              str(wb.sheetnames))
        hoja = wb["Datos"]
        check("encabezados y filas del Excel",
              hoja.max_row == 4 and hoja.cell(row=1, column=1).value == "categoria"
              and hoja.cell(row=2, column=6).value == "Super Selectos Prueba",
              "filas=%s" % hoja.max_row)
        check("filtro y panel congelado",
              hoja.freeze_panes == "A2" and hoja.auto_filter.ref is not None)
        check("CSV escrito", os.path.getsize(ruta_csv) > 100)
    except Exception as exc:  # pragma: no cover
        check("escritura de archivos", False, repr(exc))

    # --- resumen general ---
    try:
        escribir_resumen_general(
            os.path.join(dir_salida, "prueba_resumen.xlsx"),
            [{"categoria": "shop", "categoria_es": cat["etiqueta"],
              "grupo": cat["grupo"], "registros": len(filas), "con_nombre": len(filas),
              "subcategorias": 1, "archivo": "prueba_shop.xlsx",
              "por_municipio": {("San Salvador", "Municipio A"): len(filas)}}],
            [dep], {dep.nombre: [muni, distrito]}, silencioso=True)
        check("resumen general escrito",
              os.path.getsize(os.path.join(dir_salida, "prueba_resumen.xlsx")) > 1000)
    except Exception as exc:  # pragma: no cover
        check("resumen general", False, repr(exc))

    # --- cache del cliente ---
    cli = ClienteOverpass(dir_cache=os.path.join(dir_salida, "cache_prueba"),
                          pausa=0, silencioso=True)
    ruta = cli._ruta_cache("consulta de prueba")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"elements": [{"type": "node", "id": 1}]}, fh)
    datos = cli.consultar("consulta de prueba", "prueba")
    check("cache en disco se reutiliza",
          len(datos["elements"]) == 1 and cli.consultas_realizadas == 0)

    print("-- %s (%d fallas) --" % ("TODO BIEN" if not fallos else "CON FALLAS",
                                    fallos))
    print("archivos de ejemplo en: %s" % os.path.abspath(dir_salida))
    return 0 if fallos == 0 else 1


# --------------------------------------------------------------------------- #
# Linea de comandos
# --------------------------------------------------------------------------- #

def listar_categorias() -> None:
    grupo_actual = ""
    print("Categorias disponibles (%d):\n" % len(CATEGORIAS))
    for clave, cat in CATEGORIAS.items():
        if cat["grupo"] != grupo_actual:
            grupo_actual = cat["grupo"]
            print("  %s" % grupo_actual.upper())
        print("    %-18s %-32s %4d subcategorias traducidas -> %s.xlsx"
              % (clave, cat["etiqueta"], len(cat["valores"]), cat["archivo"]))
    print("\nTotal de subcategorias traducidas: %d"
          % sum(len(c["valores"]) for c in CATEGORIAS.values()))
    print("Nota: se consultan TODOS los valores de cada llave OSM, no solo los "
          "traducidos.")


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="extraer_osm.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Extrae datos de OpenStreetMap (Overpass API) de los "
                    "departamentos de San Salvador y La Libertad, El Salvador, "
                    "y los guarda en Excel por categoria.",
        epilog="""Ejemplos:
  python extraer_osm.py
  python extraer_osm.py --categorias shop office craft amenity
  python extraer_osm.py --departamentos "San Salvador" --formato ambos
  python extraer_osm.py --categorias building --division 6 --pausa 4
  python extraer_osm.py --listar-categorias
  python extraer_osm.py --diagnostico
  python extraer_osm.py --solo-excel          # Excel desde lo ya descargado
  python extraer_osm.py --autoprueba
""")
    p.add_argument("--categorias", "-c", nargs="+", metavar="CLAVE",
                   help="categorias a extraer (por defecto todas). "
                        "Ver --listar-categorias")
    p.add_argument("--departamentos", "-d", nargs="+",
                   default=list(DEPARTAMENTOS_OBJETIVO), metavar="NOMBRE",
                   help="departamentos a consultar (por defecto: San Salvador "
                        "y La Libertad)")
    p.add_argument("--salida", "-o", default=DIR_SALIDA_DEF,
                   help="directorio de salida (por defecto: %s)" % DIR_SALIDA_DEF)
    p.add_argument("--formato", "-f", choices=["excel", "csv", "ambos"],
                   default="excel", help="formato de salida (por defecto: excel)")
    p.add_argument("--cache", default=DIR_CACHE_DEF,
                   help="directorio de cache de respuestas Overpass")
    p.add_argument("--sin-cache", action="store_true",
                   help="no usar cache (siempre consulta al servidor)")
    p.add_argument("--endpoint", help="servidor Overpass preferido (URL completa)")
    p.add_argument("--timeout", type=int, default=600,
                   help="timeout de cada consulta Overpass en segundos (600)")
    p.add_argument("--pausa", type=float, default=2.0,
                   help="segundos de espera entre consultas (2.0)")
    p.add_argument("--reintentos", type=int, default=4,
                   help="reintentos por consulta antes de dividirla (4)")
    p.add_argument("--division", type=int, default=0, metavar="N",
                   help="forzar division en NxN mosaicos para todas las "
                        "categorias (0 = usar el valor propio de cada categoria)")
    p.add_argument("--sin-admin", action="store_true",
                   help="no descargar municipios/distritos ni asignarlos "
                        "(mas rapido, deja esas columnas vacias)")
    p.add_argument("--silencioso", "-q", action="store_true",
                   help="menos mensajes en pantalla")
    p.add_argument("--listar-categorias", action="store_true",
                   help="muestra las categorias y subcategorias disponibles y sale")
    p.add_argument("--solo-excel", action="store_true",
                   help="no consulta nada: genera los Excel con los datos ya "
                        "descargados en la cache (los .json de --cache)")
    p.add_argument("--diagnostico", action="store_true",
                   help="revisa el servidor y los limites, cuenta cuantos "
                        "elementos hay por categoria (sin descargarlos) y sale")
    p.add_argument("--autoprueba", action="store_true",
                   help="ejecuta pruebas internas sin usar la red y sale")
    p.add_argument("--version", action="version", version="extraer_osm %s" % VERSION)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = construir_parser().parse_args(argv)
    if args.listar_categorias:
        listar_categorias()
        return 0
    if args.autoprueba:
        return autoprueba(os.path.join(args.salida, "_autoprueba"))
    try:
        if args.solo_excel:
            return reconstruir_desde_cache(args)
        if args.diagnostico:
            claves = args.categorias or list(CATEGORIAS.keys())
            desconocidas = [c for c in claves if c not in CATEGORIAS]
            if desconocidas:
                print("Categorias desconocidas: %s" % ", ".join(desconocidas),
                      file=sys.stderr)
                return 2
            return diagnostico(crear_cliente(args), claves, args.departamentos,
                               args.silencioso)
        return ejecutar(args)
    except ErrorDependencia as exc:
        print("\nFALTA UNA DEPENDENCIA: %s" % exc, file=sys.stderr)
        return 3
    except ErrorOverpass as exc:
        print("\nERROR de Overpass: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario. Las respuestas ya descargadas "
              "quedan en la cache; vuelva a correr el script para continuar.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
