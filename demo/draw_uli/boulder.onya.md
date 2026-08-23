<!-- -*- mode: markdown -*- -->
<!-- Onya Literate: a small Boulder, Colorado graph for the draw_uli renderer demo (issue #33). -->
<!-- Facts drawn from https://en.wikipedia.org/wiki/Boulder,_Colorado and bouldercolorado.gov. -->

# @docheader

* @document: https://example.org/places/boulder-colorado
* @nodebase: https://example.org/places/boulder-colorado/
* @schema: https://schema.org/
* headline: Boulder, Colorado
* alternativeHeadline: the Flatirons and their foothills, parsed & projected with Onya
* comment: ọ́nyà ugwu: Boulder's own web of foothills and creek
  * keywords: decoration
* @interpretations:
    * population: number
    * elevation: number
    * foundingDate: datetime
    * termStart: datetime
    * termEnd: datetime
    * numberOfStudents: number
    * numberOfEmployees: number

# Boulder [City Place]

* name: Boulder
* description: A home-rule city in Boulder County, Colorado, at the foot of the Rocky Mountains' Front Range, where the mountains meet the Great Plains.
* foundingDate: "1858"
  * note: Founded by prospectors led by Thomas Aikins after gold was found along Boulder Creek; incorporated as a city on 1871-11-04.
* elevation: "5269"
  * unitText: ft
* population: "108250"
  * asOf: "2020"
  * source: 2020 United States Census
<!-- metaproperty demo: the mayor edge itself carries the term as nested assertions, rather than
     a separate Role scaffold node -- Onya's preferred style for relationship metadata. -->
* mayor -> AaronBrockett
  * termStart: "2023"
  * termEnd: "2026"
  * note: Boulder's first directly elected mayor; previously the mayor was chosen by the City Council from among its own members.
* nearestMajorCity -> Denver
  * distance: "25 mi"

# AaronBrockett [Person]

* name: Aaron Brockett
* jobTitle: Mayor of Boulder
* description: Elected in November 2023 as Boulder's first popularly elected mayor.

# Denver [City Place]

* name: Denver
* description: Capital and most populous city of Colorado, about 25 miles southeast of Boulder.

# Flatirons [Place]

* name: The Flatirons
* description: Five numbered slabs of tilted Fountain Formation sandstone on Boulder's western skyline, among the most photographed rock formations in Colorado.
* containedInPlace -> Boulder

# BoulderCreek [RiverBodyOfWater Place]

* name: Boulder Creek
* description: The creek along which gold was discovered in early 1859, drawing the prospectors who founded the city; today followed by the Boulder Creek Path.
* containedInPlace -> Boulder

# PearlStreetMall [Place]

* name: Pearl Street Mall
* description: A four-block pedestrian shopping and dining district in downtown Boulder, closed to vehicle traffic since the 1970s.
* containedInPlace -> Boulder

# CUBoulder [CollegeOrUniversity]

* name: University of Colorado Boulder
* description: Flagship campus of the University of Colorado system, chartered in 1861 and opened in 1877; the city's largest employer.
* location -> Boulder
* numberOfStudents: "37000"
  * note: approximate combined undergraduate and graduate enrollment

# NCAR [Organization]

* name: National Center for Atmospheric Research
* description: Federally funded atmospheric and climate science laboratory headquartered in Boulder.
* location -> Boulder

# NISTBoulder [GovernmentOrganization]

* name: NIST Boulder Laboratories
* description: The Boulder campus of the National Institute of Standards and Technology, home to timing and frequency-standards research.
* location -> Boulder

# NOAABoulder [GovernmentOrganization]

* name: NOAA Boulder
* description: Boulder laboratories of the National Oceanic and Atmospheric Administration, focused on atmospheric and space weather research.
* location -> Boulder

# BallCorporation [Organization]

* name: Ball Corporation
* description: Aerospace and packaging company, and one of Boulder's largest private employers.
* location -> Boulder
* numberOfEmployees: "4800"

# BolderBoulder [SportsEvent]

* name: Bolder Boulder
* description: A 10-kilometer road race run every Memorial Day since 1979, drawing tens of thousands of participants through Boulder's streets.
* location -> Boulder
* foundingDate: "1979"
