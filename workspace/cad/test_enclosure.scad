// Parametric PCB Enclosure: test_enclosure
// Generated automatically by Odysseus CAD Maker

$fn = 40;

pcb_w = 40.0;
pcb_l = 50.0;
box_h = 20.0;
wall = 2.0;
standoff_h = 5.0;
screw_d = 2.2;

outer_w = pcb_w + 2 * (wall + 1);
outer_l = pcb_l + 2 * (wall + 1);
outer_h = box_h + wall;

module standoff(x, y) {
    translate([x, y, wall]) {
        difference() {
            cylinder(r=screw_d + 1.5, h=standoff_h);
            cylinder(r=screw_d / 2, h=standoff_h + 1);
        }
    }
}

module enclosure_base() {
    difference() {
        // Outer body
        cube([outer_w, outer_l, outer_h]);
        // Inner cavity
        translate([wall, wall, wall])
            cube([outer_w - 2 * wall, outer_l - 2 * wall, outer_h]);
    }

    // PCB Standoffs in 4 corners
    standoff(wall + 4, wall + 4);
    standoff(outer_w - wall - 4, wall + 4);
    standoff(wall + 4, outer_l - wall - 4);
    standoff(outer_w - wall - 4, outer_l - wall - 4);
}

module enclosure_lid() {
    translate([outer_w + 10, 0, 0]) {
        difference() {
            union() {
                cube([outer_w, outer_l, wall]);
                translate([wall + 0.3, wall + 0.3, wall])
                    cube([outer_w - 2 * wall - 0.6, outer_l - 2 * wall - 0.6, 2]);
            }
            // Screw holes
            translate([wall + 4, wall + 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([outer_w - wall - 4, wall + 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([wall + 4, outer_l - wall - 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
            translate([outer_w - wall - 4, outer_l - wall - 4, -1]) cylinder(r=screw_d / 2, h=wall + 4);
        }
    }
}

enclosure_base();
enclosure_lid();
