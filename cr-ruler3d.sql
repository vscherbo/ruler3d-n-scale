-- shp.ruler3d определение

-- Drop table

-- DROP TABLE shp.ruler3d;

CREATE TABLE shp.ruler3d (
	shp_id int4 NOT NULL,
	box int4 NOT NULL,
	length numeric NULL,
	width numeric NULL,
	height numeric NULL,
	ins_ts timestamp DEFAULT now() NOT NULL,
	CONSTRAINT ruler3d_pk PRIMARY KEY (shp_id, box)
);
