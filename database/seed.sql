INSERT INTO locations(slug,name,state,country)
VALUES ('bhopal','Bhopal','Madhya Pradesh','India')
ON CONFLICT(slug) DO NOTHING;

INSERT INTO tourists(tourist_id,location_slug,display_name)
VALUES ('T001','bhopal','Demo Tourist 1'),('T002','bhopal','Demo Tourist 2'),('T003','bhopal','Demo Tourist 3')
ON CONFLICT(tourist_id) DO NOTHING;
