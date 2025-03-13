// File: gpio_pulse.c
#include <gpiod.h>
#include <stdio.h>
#include <time.h>
#include <stdlib.h>

void generate_pulse(const char *chip_name, int gpio_line) {
    struct gpiod_chip *chip;
    struct gpiod_line *line;
    struct timespec delay = {0, 10000};  // 10 µs

    // Open GPIO chip
    chip = gpiod_chip_open(chip_name);
    if (!chip) {
        perror("Failed to open GPIO chip");
        return;
    }

    // Get GPIO line
    line = gpiod_chip_get_line(chip, gpio_line);
    if (!line) {
        perror("Failed to get GPIO line");
        gpiod_chip_close(chip);
        return;
    }

    // Request GPIO line as output
    if (gpiod_line_request_output(line, "pulse_generator", 0) < 0) {
        perror("Failed to request GPIO line as output");
        gpiod_chip_close(chip);
        return;
    }

    // Generate pulse
    gpiod_line_set_value(line, 1);  // Set HIGH
    clock_nanosleep(CLOCK_MONOTONIC, 0, &delay, NULL);
    gpiod_line_set_value(line, 0);  // Set LOW

    // Release resources
    gpiod_line_release(line);
    gpiod_chip_close(chip);
}

