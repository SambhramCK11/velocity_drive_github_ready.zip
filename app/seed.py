"""Seed fleet data.

Each car carries a hand-written ``description`` and ``tagline``. Those fields
are not just marketing copy: they are the corpus the TF-IDF recommender
indexes, so the natural-language search quality depends on them.
"""

from __future__ import annotations

import json
import sqlite3

# (slug, make, model, year, category, body_style, transmission, fuel, seats,
#  doors, luggage, hp, 0-100, daily_rate, deposit, rating, rentals, units,
#  color, accent_hex, art_style, features, tagline, description)
FLEET: list[dict] = [
    dict(
        slug="lamborghini-huracan-evo",
        make="Lamborghini", model="Huracan EVO", year=2024,
        category="Supercar", body_style="Coupe", transmission="Automatic",
        fuel_type="Petrol", seats=2, doors=2, luggage=1, horsepower=640,
        zero_to_hundred=2.9, daily_rate=3200, deposit=5000, rating=4.9,
        rental_count=184, total_units=2, color="Arancio Borealis",
        accent_hex="#ff7a18", art_style="supercar",
        features=["Launch Control", "Carbon Ceramic Brakes", "Apple CarPlay",
                  "Sport Exhaust", "Lifting System", "Alcantara Interior"],
        tagline="The loudest way to arrive anywhere.",
        description=(
            "A naturally aspirated V10 supercar built for weekend drives down "
            "Jumeirah Beach Road and photo stops at the Burj Al Arab. Extreme "
            "performance, exotic styling, razor sharp handling and a soundtrack "
            "that turns heads. Ideal for special occasions, birthdays, luxury "
            "photoshoots, content creation and anyone who wants a fast flashy "
            "exotic sports car experience rather than practical transport."
        ),
    ),
    dict(
        slug="ferrari-portofino-m",
        make="Ferrari", model="Portofino M", year=2023,
        category="Supercar", body_style="Convertible", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=2, luggage=2, horsepower=620,
        zero_to_hundred=3.45, daily_rate=2950, deposit=5000, rating=4.8,
        rental_count=141, total_units=1, color="Rosso Corsa",
        accent_hex="#e01e2b", art_style="convertible",
        features=["Retractable Hardtop", "Magnaride Suspension", "Bluetooth",
                  "Heated Seats", "Reversing Camera", "Carbon Fibre Trim"],
        tagline="Drop the roof, keep the drama.",
        description=(
            "A convertible grand tourer that folds its hardtop in fourteen "
            "seconds. Fast and glamorous but far more usable than a hard core "
            "supercar, with two small rear seats and real luggage space. "
            "Perfect for open top coastal cruising, romantic evenings, "
            "anniversaries and couples who want an exotic car they can "
            "actually drive comfortably for a few hours."
        ),
    ),
    dict(
        slug="rolls-royce-ghost",
        make="Rolls-Royce", model="Ghost", year=2024,
        category="Luxury", body_style="Sedan", transmission="Automatic",
        fuel_type="Petrol", seats=5, doors=4, luggage=3, horsepower=563,
        zero_to_hundred=4.8, daily_rate=4100, deposit=7500, rating=5.0,
        rental_count=96, total_units=1, color="English White",
        accent_hex="#d8d3c4", art_style="luxury-sedan",
        features=["Starlight Headliner", "Rear Executive Seats", "Massage Seats",
                  "Chauffeur Partition", "Bespoke Audio", "Champagne Cooler"],
        tagline="Silence, engineered.",
        description=(
            "The definitive chauffeur driven limousine. Whisper quiet cabin, "
            "starlight headliner and rear seats that recline. This is the car "
            "for weddings, executive airport transfers, corporate VIP guests, "
            "red carpet arrivals and formal business events where arriving "
            "with understated prestige and total comfort matters more than "
            "outright speed."
        ),
    ),
    dict(
        slug="mercedes-s500",
        make="Mercedes-Benz", model="S 500 L", year=2024,
        category="Luxury", body_style="Sedan", transmission="Automatic",
        fuel_type="Petrol", seats=5, doors=4, luggage=3, horsepower=429,
        zero_to_hundred=4.9, daily_rate=1250, deposit=3000, rating=4.8,
        rental_count=312, total_units=4, color="Obsidian Black",
        accent_hex="#9aa7b4", art_style="luxury-sedan",
        features=["Burmester 3D Audio", "Rear Entertainment", "Massage Seats",
                  "Ambient Lighting", "Adaptive Cruise", "Wireless CarPlay"],
        tagline="The executive standard.",
        description=(
            "The benchmark executive saloon for business travel. Long "
            "wheelbase rear legroom, massaging seats and an air suspension "
            "that erases road noise on the Sheikh Zayed Road. The sensible "
            "professional choice for corporate clients, consultants, airport "
            "pickups and multi day business trips where comfort, discretion "
            "and a quiet cabin for calls matter most."
        ),
    ),
    dict(
        slug="bmw-m4-competition",
        make="BMW", model="M4 Competition", year=2024,
        category="Sports", body_style="Coupe", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=2, luggage=2, horsepower=503,
        zero_to_hundred=3.5, daily_rate=1150, deposit=3000, rating=4.7,
        rental_count=268, total_units=3, color="Isle of Man Green",
        accent_hex="#1f7a4d", art_style="sports-coupe",
        features=["M Sport Exhaust", "Carbon Bucket Seats", "Head Up Display",
                  "Drift Analyser", "Harman Kardon Audio", "Apple CarPlay"],
        tagline="Track focus, street legal.",
        description=(
            "A twin turbo straight six coupe that bridges daily usability and "
            "genuine performance. Quick, aggressive and engaging to drive, but "
            "with a usable boot and rear seats. A strong pick for driving "
            "enthusiasts, track day spectators and younger renters who want "
            "something fast and sporty without full supercar running costs."
        ),
    ),
    dict(
        slug="porsche-911-carrera",
        make="Porsche", model="911 Carrera S", year=2024,
        category="Sports", body_style="Coupe", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=2, luggage=2, horsepower=443,
        zero_to_hundred=3.5, daily_rate=1650, deposit=4000, rating=4.9,
        rental_count=203, total_units=2, color="GT Silver",
        accent_hex="#b9bdc2", art_style="sports-coupe",
        features=["Sport Chrono", "PASM Suspension", "Bose Audio",
                  "Lane Keep Assist", "Wireless CarPlay", "Sport Seats Plus"],
        tagline="The everyday exotic.",
        description=(
            "The sports car you can genuinely use every day. Precise steering, "
            "rear engine balance and build quality that shrugs off long "
            "distance driving. Suits renters who want serious performance and "
            "prestige but also comfort, reliability and enough practicality "
            "for a weekend away or a long desert highway road trip."
        ),
    ),
    dict(
        slug="range-rover-vogue",
        make="Land Rover", model="Range Rover Vogue", year=2024,
        category="SUV", body_style="SUV", transmission="Automatic",
        fuel_type="Petrol", seats=5, doors=5, luggage=4, horsepower=395,
        zero_to_hundred=6.0, daily_rate=1450, deposit=3500, rating=4.8,
        rental_count=287, total_units=4, color="Santorini Black",
        accent_hex="#3c4a5a", art_style="suv",
        features=["Air Suspension", "Terrain Response", "Meridian Audio",
                  "Panoramic Roof", "Heated Rear Seats", "360 Camera"],
        tagline="Command every surface.",
        description=(
            "Commanding luxury SUV with genuine off road ability and a cabin "
            "that isolates you from everything outside. Handles desert tracks, "
            "school runs and hotel valets with equal confidence. A favourite "
            "for families, desert safari trips, golf weekends and anyone who "
            "wants a high driving position with premium comfort and space."
        ),
    ),
    dict(
        slug="toyota-land-cruiser",
        make="Toyota", model="Land Cruiser 300", year=2024,
        category="SUV", body_style="SUV", transmission="Automatic",
        fuel_type="Petrol", seats=7, doors=5, luggage=4, horsepower=409,
        zero_to_hundred=6.7, daily_rate=720, deposit=2000, rating=4.7,
        rental_count=421, total_units=6, color="Pearl White",
        accent_hex="#c8ccd0", art_style="suv",
        features=["7 Seats", "4WD Low Range", "Roof Rails", "Cooled Seats",
                  "Apple CarPlay", "Cruise Control"],
        tagline="Goes anywhere, carries everyone.",
        description=(
            "The workhorse of the region. Seven seats, proper four wheel drive "
            "and legendary reliability in heat and sand. The default choice for "
            "large families, group trips, dune bashing, camping in Hatta and "
            "long intercity drives to Abu Dhabi or Oman where space, "
            "durability and running cost matter more than styling."
        ),
    ),
    dict(
        slug="nissan-patrol-platinum",
        make="Nissan", model="Patrol Platinum", year=2023,
        category="SUV", body_style="SUV", transmission="Automatic",
        fuel_type="Petrol", seats=7, doors=5, luggage=4, horsepower=400,
        zero_to_hundred=6.8, daily_rate=650, deposit=2000, rating=4.6,
        rental_count=388, total_units=5, color="Gun Metallic",
        accent_hex="#6b7280", art_style="suv",
        features=["7 Seats", "4WD", "Around View Monitor", "Bose Audio",
                  "Rear Climate Control", "Tow Package"],
        tagline="The desert's favourite.",
        description=(
            "A big comfortable V8 family SUV built for the Gulf. Cools fast in "
            "summer, seats seven adults and tows easily. Popular for extended "
            "family holidays, group airport runs, weekend desert camping and "
            "anyone needing maximum passenger and luggage capacity at a "
            "reasonable mid range daily price."
        ),
    ),
    dict(
        slug="tesla-model-3-lr",
        make="Tesla", model="Model 3 Long Range", year=2025,
        category="Electric", body_style="Sedan", transmission="Automatic",
        fuel_type="Electric", seats=5, doors=4, luggage=3, horsepower=394,
        zero_to_hundred=4.4, daily_rate=420, deposit=1500, rating=4.7,
        rental_count=502, total_units=8, color="Deep Blue Metallic",
        accent_hex="#2f6df6", art_style="ev-sedan",
        features=["Autopilot", "629km Range", "Glass Roof", "Supercharging",
                  "Premium Audio", "Sentry Mode"],
        tagline="Zero fuel stops, zero fuss.",
        description=(
            "Quick, quiet and cheap to run with no petrol costs at all. "
            "Excellent for cost conscious renters, tech enthusiasts, "
            "environmentally minded travellers and long monthly rentals where "
            "fuel savings compound. Instant torque makes it feel fast in city "
            "traffic while Autopilot eases motorway commuting."
        ),
    ),
    dict(
        slug="tesla-model-y",
        make="Tesla", model="Model Y", year=2025,
        category="Electric", body_style="SUV", transmission="Automatic",
        fuel_type="Electric", seats=5, doors=5, luggage=4, horsepower=384,
        zero_to_hundred=5.0, daily_rate=460, deposit=1500, rating=4.6,
        rental_count=364, total_units=6, color="Pearl White",
        accent_hex="#5b8def", art_style="ev-sedan",
        features=["Autopilot", "Huge Boot", "Glass Roof", "Supercharging",
                  "Heat Pump", "Wireless Charging"],
        tagline="Electric space, family sized.",
        description=(
            "A practical electric crossover with a cavernous boot and a high "
            "seating position. Combines low running costs with family "
            "friendly space, making it a smart pick for small families, "
            "longer stays, airport trips with lots of luggage and renters who "
            "want an electric car but need more room than a saloon."
        ),
    ),
    dict(
        slug="mercedes-v-class",
        make="Mercedes-Benz", model="V-Class Avantgarde", year=2023,
        category="Van", body_style="MPV", transmission="Automatic",
        fuel_type="Diesel", seats=8, doors=5, luggage=6, horsepower=237,
        zero_to_hundred=8.1, daily_rate=890, deposit=2500, rating=4.6,
        rental_count=156, total_units=3, color="Cavansite Blue",
        accent_hex="#274b8a", art_style="van",
        features=["8 Seats", "Conference Seating", "Rear Climate",
                  "Electric Sliding Doors", "Large Luggage Bay", "USB-C Ports"],
        tagline="Move the whole team.",
        description=(
            "An eight seat luxury people mover with conference style seating "
            "and a huge luggage bay. Built for corporate group transfers, "
            "conference delegations, large family arrivals, wedding party "
            "transport and tour groups who need everyone plus all the suitcases "
            "in one comfortable air conditioned vehicle."
        ),
    ),
    dict(
        slug="bentley-continental-gt",
        make="Bentley", model="Continental GT", year=2024,
        category="Luxury", body_style="Coupe", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=2, luggage=2, horsepower=550,
        zero_to_hundred=4.0, daily_rate=2400, deposit=5000, rating=4.9,
        rental_count=112, total_units=1, color="Glacier White",
        accent_hex="#e6e2d6", art_style="luxury-coupe",
        features=["Rotating Display", "Naim Audio", "Diamond Quilted Leather",
                  "All Wheel Drive", "Massage Seats", "Night Vision"],
        tagline="Grand touring, perfected.",
        description=(
            "A grand tourer that crosses continents in hand stitched comfort. "
            "Enormous effortless torque paired with a cabin of quilted leather "
            "and machined metal. Chosen for milestone celebrations, luxury "
            "road trips, elegant wedding cars and clients who want prestige "
            "and craftsmanship rather than aggressive supercar styling."
        ),
    ),
    dict(
        slug="audi-q8-quattro",
        make="Audi", model="Q8 55 TFSI", year=2024,
        category="SUV", body_style="SUV", transmission="Automatic",
        fuel_type="Petrol", seats=5, doors=5, luggage=4, horsepower=335,
        zero_to_hundred=5.9, daily_rate=980, deposit=2500, rating=4.7,
        rental_count=234, total_units=3, color="Navarra Blue",
        accent_hex="#1d4f91", art_style="suv",
        features=["Quattro AWD", "Virtual Cockpit", "Bang & Olufsen Audio",
                  "Adaptive Air Suspension", "Matrix LED", "360 Camera"],
        tagline="Sharp suit, big boots.",
        description=(
            "A coupe styled premium SUV that mixes sporty road manners with "
            "family practicality. Quattro all wheel drive, a sharp digital "
            "cockpit and a modern understated design. Good for business "
            "travellers with luggage, small families wanting something "
            "stylish, and renters after a premium SUV that is less imposing "
            "than a full size off roader."
        ),
    ),
    dict(
        slug="ford-mustang-gt",
        make="Ford", model="Mustang GT", year=2024,
        category="Sports", body_style="Convertible", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=2, luggage=2, horsepower=486,
        zero_to_hundred=4.4, daily_rate=690, deposit=2000, rating=4.5,
        rental_count=319, total_units=4, color="Race Red",
        accent_hex="#cf2027", art_style="convertible",
        features=["V8 Engine", "Soft Top Convertible", "Track Apps",
                  "B&O Audio", "Launch Control", "Apple CarPlay"],
        tagline="Affordable American muscle.",
        description=(
            "A V8 convertible that delivers genuine noise and drama for a "
            "fraction of supercar money. Roof down cruising along the beach, "
            "loud exhaust and classic muscle car styling. The value option for "
            "renters who want a fun exciting weekend car, a memorable birthday "
            "drive or an open top experience on a moderate budget."
        ),
    ),
    dict(
        slug="toyota-corolla-hybrid",
        make="Toyota", model="Corolla Hybrid", year=2024,
        category="Economy", body_style="Sedan", transmission="Automatic",
        fuel_type="Hybrid", seats=5, doors=4, luggage=2, horsepower=138,
        zero_to_hundred=9.2, daily_rate=135, deposit=800, rating=4.5,
        rental_count=784, total_units=12, color="Silver Metallic",
        accent_hex="#8e979f", art_style="sedan",
        features=["Hybrid Economy", "Apple CarPlay", "Lane Assist",
                  "Reversing Camera", "Cruise Control", "Bluetooth"],
        tagline="Cheap to run, easy to park.",
        description=(
            "The sensible budget choice. Hybrid fuel economy, low daily rate "
            "and effortless city driving. Ideal for students, long stay "
            "visitors, daily commuting, ride hailing work and anyone who wants "
            "the cheapest reliable automatic car for getting around Dubai "
            "without worrying about fuel bills or parking size."
        ),
    ),
    dict(
        slug="nissan-sunny",
        make="Nissan", model="Sunny", year=2024,
        category="Economy", body_style="Sedan", transmission="Automatic",
        fuel_type="Petrol", seats=5, doors=4, luggage=2, horsepower=99,
        zero_to_hundred=11.5, daily_rate=99, deposit=700, rating=4.2,
        rental_count=912, total_units=15, color="Brilliant Silver",
        accent_hex="#a6adb4", art_style="sedan",
        features=["Bluetooth", "Reversing Camera", "USB Charging",
                  "Air Conditioning", "Cruise Control", "Automatic"],
        tagline="The lowest daily rate we offer.",
        description=(
            "Our most affordable car. Simple, economical and perfectly "
            "adequate for getting from A to B. The best value for tight "
            "budgets, short errands, first time renters, students and long "
            "monthly hires where the priority is the cheapest possible price "
            "rather than performance, badge or luxury features."
        ),
    ),
    dict(
        slug="mini-cooper-s",
        make="MINI", model="Cooper S", year=2024,
        category="Compact", body_style="Hatchback", transmission="Automatic",
        fuel_type="Petrol", seats=4, doors=3, luggage=1, horsepower=201,
        zero_to_hundred=6.6, daily_rate=310, deposit=1200, rating=4.6,
        rental_count=298, total_units=5, color="Chili Red",
        accent_hex="#d6373f", art_style="hatchback",
        features=["Go Kart Handling", "Harman Kardon Audio", "Panoramic Roof",
                  "Apple CarPlay", "Sport Mode", "Ambient Lighting"],
        tagline="Small car, big personality.",
        description=(
            "A fun compact hatchback with sharp go kart handling and retro "
            "styling. Easy to park in tight mall garages but genuinely "
            "entertaining on a back road. Suits couples, solo travellers, city "
            "driving and renters who want character and a bit of fun without "
            "paying sports car prices or dealing with a large vehicle."
        ),
    ),
]


def seed_fleet(conn: sqlite3.Connection) -> int:
    """Insert the fleet. Returns the number of cars written."""
    rows = [
        (
            c["slug"], c["make"], c["model"], c["year"], c["category"],
            c["body_style"], c["transmission"], c["fuel_type"], c["seats"],
            c["doors"], c["luggage"], c["horsepower"], c["zero_to_hundred"],
            c["daily_rate"], c["deposit"], c["rating"], c["rental_count"],
            c["total_units"], c["color"], c["accent_hex"], c["art_style"],
            json.dumps(c["features"]), c["tagline"], c["description"],
        )
        for c in FLEET
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO cars (
            slug, make, model, year, category, body_style, transmission,
            fuel_type, seats, doors, luggage, horsepower, zero_to_hundred,
            daily_rate, deposit, rating, rental_count, total_units, color,
            accent_hex, art_style, features, tagline, description
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)
