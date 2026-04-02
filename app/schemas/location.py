from pydantic import BaseModel


class LocationPrediction(BaseModel):
    place_id: str
    description: str
    main_text: str
    secondary_text: str


class LocationSearchResponse(BaseModel):
    predictions: list[LocationPrediction]


class LocationDetailsResponse(BaseModel):
    place_id: str
    display_name: str
    latitude: float
    longitude: float


class TimezoneResponse(BaseModel):
    zone_name: str
    gmt_offset: int
    abbreviation: str
    dst: bool
